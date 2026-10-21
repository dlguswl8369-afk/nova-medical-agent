import json
import hashlib
import collections
import copy
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from nova_sdk import NovaError
from nova_retrieval import BM25Index
from .context import fact, observation_text, query_from_facts, reference_packet, visible_facts
from .record import render_record, fallback_record
from .prompts import STEP, RECORD
from .budget import Budget
from .diagnostics import parse_object, parse_action, rejection_event
from .action_repair import repair_request
from .record_budget import RecordEnvelope, RECORD_REPAIR, fit_record_envelope, input_charge, messages_for
from .experiment_config import STRATEGY
from .clinical_strategy import features, call_settings, step_prompt, plan_text, examination_choice, audit_action, PLAN, AUDIT

MODEL = 'openai/gpt-6-luna'
TRANSIENT = {'PROVIDER_UNAVAILABLE', 'PROVIDER_RESPONSE_INVALID', 'PATIENT_RESPONSE_INVALID', 'EXAMINER_RESPONSE_INVALID', 'API_UNAVAILABLE', 'REQUEST_PENDING', 'LOCAL_GATEWAY_UNAVAILABLE'}
REGENERATE = {'PROVIDER_RESPONSE_INVALID', 'PATIENT_RESPONSE_INVALID', 'EXAMINER_RESPONSE_INVALID'}
CLOSED = {'SESSION_EXPIRED', 'SESSION_CLOSED', 'RUN_NOT_ACTIVE'}
TURN_REJECTIONS = {'EXAM_NOT_SPECIFIC', 'EXAM_NOT_RECOGNIZED', 'CONTENT_TOO_LONG', 'EMPTY_CONTENT'}


def safe_error(code):
    return code if isinstance(code, str) and re.fullmatch('[A-Z_]{1,80}', code) else 'UNCLASSIFIED_API_ERROR'


@dataclass(frozen=True)
class Config:
    max_turns: int = 30
    max_doctor_requests: int = 80
    max_input_budget: int = 500000
    max_output_budget: int = 100000
    reference_chars: int = 12000
    fact_chars: int = 22000
    time_margin: int = 300
    attempts: int = 3
    retry_delay: float = 1.0

    def __post_init__(self):
        if not (0 <= self.max_turns <= 50 and 1 <= self.max_doctor_requests <= 200 and 1 <= self.attempts <= 3):
            raise ValueError('INVALID_LIMIT_CONFIG')
        if not (0 < self.max_input_budget <= 500000 and 0 < self.max_output_budget <= 100000):
            raise ValueError('INVALID_TOKEN_LIMIT_CONFIG')
        if not (128 <= self.reference_chars <= 16000 and 1000 <= self.fact_chars <= 24000):
            raise ValueError('INVALID_CONTEXT_CONFIG')
        if not (0 <= self.retry_delay <= 10 and 30 <= self.time_margin <= 600):
            raise ValueError('INVALID_TIME_CONFIG')


@dataclass
class State:
    index: BM25Index
    config: Config = field(default_factory=Config)
    report: dict = field(default_factory=dict)
    strategy: str = STRATEGY


def prepare():
    path = os.environ.get('NOVA_RAG_INDEX', str(Path(__file__).resolve().parents[1] / 'indexes/bm25_ko.json.gz'))
    # No patient access, SDK call, network, or writable cache during prepare.
    root = Path(os.environ.get('NOVA_GUIDELINES_DIR', '/opt/nova/guidelines'))
    sources = os.environ.get('NOVA_RAG_SOURCES', 'auto')
    if sources == 'auto':
        sources = 'legacy,guidelines' if root.is_dir() else 'legacy'
    if sources not in ('legacy', 'guidelines', 'legacy,guidelines', 'none'):
        raise ValueError('INVALID_RAG_SOURCES')
    legacy = BM25Index.load(path) if 'legacy' in sources else None
    if sources == 'legacy':
        return State(legacy)
    from nova_retrieval.guidelines import CombinedIndex, GuidelinesIndex
    guidelines = None
    if 'guidelines' in sources:
        database = os.environ.get('NOVA_GUIDELINES_INDEX', str(Path(__file__).resolve().parents[1] / 'indexes/guidelines.sqlite'))
        guidelines = GuidelinesIndex(database, root)
    return State(CombinedIndex(legacy, guidelines))


class Run:
    def __init__(self, client, state, session):
        self.client, self.state, self.config, self.session = client, state, state.config, session
        self.facts, self.explanations = [], []
        self.features = features(state.strategy)
        self.step_prompt = step_prompt(STEP, state.strategy)
        self.clinical_plan = None
        self.plan_attempted, self.audit_attempted = False, False
        self.failed_exams, self.last_exam_failure = set(), None
        self.reference_cache = None  # Last query only; session memory, never disk.
        self.report = {'model': MODEL, 'doctor_http_attempts': 0, 'doctor_unique_requests': 0, 'doctor_successes': 0,
            'input_budget_reserved': 0, 'output_budget_reserved': 0, 'reported_prompt_tokens': 0, 'reported_completion_tokens': 0,
            'usage_missing_responses': 0, 'action_attempts': 0, 'actions_succeeded': 0, 'invalid_model_outputs': 0,
            'errors': [], 'retrieval_calls': 0, 'retrieval_cache_hits': 0, 'empty_retrievals': 0, 'max_reference_chars': 0, 'max_prompt_chars': 0,
            'reference_packets': [], 'query_selection': [], 'action_counts': {}, 'model_retries': 0, 'action_retries': 0,
            'submitted': False, 'degraded': False, 'diagnosis_accuracy_evaluated': False, 'clinical_record_quality_evaluated': False}
        state.report = self.report
        self.report.update(strategy=state.strategy, auxiliary_events=[], examination_choices=[])
        self.budget = Budget(self.config.max_input_budget, self.config.max_output_budget, self.config.max_doctor_requests)
        self.report.update(rejection_events=[], action_sequence=[], final_http_attempts=0,
            termination_reason=None, termination_kind=None, record_outcome=None,
            pre_call_input_estimates_sum=0, pre_call_output_caps_sum=0)
        self.sync_budget()
        self.record_user = None
        self.record_envelope = None
        self.report.update(record_envelope_checks=[], record_context_packing=[], action_record_headrooms=[], action_repairs=[])
        self.deadline = datetime.fromisoformat(session['deadline']).timestamp() if session.get('deadline') else time.time() + 1800
        self.started = time.monotonic()

    def left(self):
        return min(self.deadline - time.time(), 1800 - (time.monotonic() - self.started))

    def error(self, code):
        # Error codes only. Never log exception strings, keys or raw HTTP bodies.
        self.report['errors'].append(safe_error(code))

    def sync_budget(self):
        snapshot = self.budget.snapshot()
        self.report['budget_ledger'] = snapshot
        self.report.update(input_budget_reserved=snapshot['committed_input'],
            output_budget_reserved=snapshot['committed_output'],
            reported_prompt_tokens=snapshot['confirmed_input'], reported_completion_tokens=snapshot['confirmed_output'],
            usage_missing_responses=snapshot['invalid_usage_responses'],
            doctor_http_attempts=snapshot['http_attempts'], doctor_unique_requests=snapshot['unique_requests'])

    def reject(self, exc, phase):
        self.report['invalid_model_outputs'] += 1
        self.report['rejection_events'].append(rejection_event(exc, phase, self.report['doctor_http_attempts']))

    def stop(self, reason, kind):
        self.report.update(termination_reason=reason, termination_kind=kind)

    def doctor(self, system, user, final=False, purpose='ACTION'):
        if purpose not in ('ACTION', 'PLAN', 'AUDIT') or (final and purpose != 'ACTION'):
            raise ValueError('INVALID_DOCTOR_PURPOSE')
        cfg, report = self.config, self.report
        auxiliary = purpose != 'ACTION'
        messages = messages_for(system, user)
        limit = 4096 if final else 2048
        effort = 'medium'
        if auxiliary:
            limit, effort = call_settings(self.state.strategy, purpose, self.left() - cfg.time_margin)
        # UTF-8 bytes + structural allowance conservatively bound byte-BPE tokens.
        charge = input_charge(system, user)
        if charge > 100000:
            raise NovaError('LOCAL_SINGLE_PROMPT_BUDGET')
        record_attempts = min(cfg.attempts, cfg.max_doctor_requests)
        if not final:
            # Use current observed context, not the ACTION format-repair suffix.
            envelope = RecordEnvelope(self.record_user if self.record_user is not None else user, record_attempts)
            if max(envelope.charges) > 100000:
                raise NovaError('LOCAL_FINAL_CONTEXT_BUDGET')
            headroom = envelope.headroom()
            self.report['action_record_headrooms'].append(envelope.audit())
        elif self.record_envelope is None:
            self.record_envelope = RecordEnvelope(user, record_attempts)
        request_id = str(uuid.uuid4())
        fingerprint = hashlib.sha256(json.dumps([messages, limit, MODEL, effort], ensure_ascii=False).encode()).hexdigest()
        for attempt in range(1 if auxiliary else cfg.attempts):
            if self.left() <= 10:
                raise NovaError('LOCAL_DEADLINE')
            if final and report['final_http_attempts'] >= record_attempts:
                raise NovaError('LOCAL_FINAL_RETRY_BUDGET')
            if final:
                ordinal = report['final_http_attempts']
                self.record_envelope.validate(system, user, ordinal)
                headroom = self.record_envelope.headroom(ordinal + 1)
                report['record_envelope_checks'].append({'attempt': ordinal + 1,
                    'actual_input_estimate': charge, 'enforced_input_cap': self.record_envelope.charges[ordinal],
                    'remaining_retry_input_headroom': headroom[0], 'context_and_suffix_validated': True})
            try:
                self.budget.reserve(request_id, charge, limit, fingerprint, headroom=headroom,
                    phase='RECORD' if final else purpose)
            finally:
                self.sync_budget()
            report['final_http_attempts'] += int(final)
            report['pre_call_input_estimates_sum'] += charge
            report['pre_call_output_caps_sum'] += limit
            # Avoid starting a 240-second request near the session deadline.
            if hasattr(self.client, 'timeout'):
                self.client.timeout = max(1, min(240, self.left() - 5))
                if auxiliary:
                    self.client.timeout = max(1, min(180 if effort == 'high' else 120, self.left() - cfg.time_margin))
            try:
                response = self.client.chat(messages, max_tokens=limit, reasoning_effort=effort, model=MODEL, request_id=request_id)
                report['doctor_successes'] += 1
                self.budget.settle(request_id, response.get('usage') if isinstance(response, dict) else None)
                self.sync_budget()
                return response['choices'][0]['message']['content']
            except (NovaError, TimeoutError, OSError) as exc:
                if not isinstance(exc, NovaError):
                    exc = NovaError('API_UNAVAILABLE')
                self.error(exc.code)
                if auxiliary or exc.code not in TRANSIENT or attempt + 1 == cfg.attempts:
                    raise exc from None
                report['model_retries'] += 1
                if exc.code in REGENERATE:
                    request_id = str(uuid.uuid4())
                time.sleep(min(cfg.retry_delay, max(0, self.left() - 10)))
            except (KeyError, TypeError, IndexError, AttributeError):
                raise ValueError('MALFORMED_COMPLETION') from None
            finally:
                self.sync_budget()

    def action(self, action, **kwargs):
        request_id = str(uuid.uuid4())
        method = {'SAY': self.client.say, 'EXAM': self.client.exam, 'DIAGNOSE': self.client.diagnose}[action]
        for attempt in range(self.config.attempts):
            if self.left() <= 2:
                raise NovaError('LOCAL_DEADLINE')
            self.report['action_attempts'] += 1
            if hasattr(self.client, 'timeout'):
                self.client.timeout = max(1, min(240, self.left() - 1))
            try:
                return method(request_id=request_id, **kwargs)
            except (NovaError, TimeoutError, OSError) as exc:
                if not isinstance(exc, NovaError):
                    exc = NovaError('API_UNAVAILABLE')
                self.error(exc.code)
                if exc.code not in TRANSIENT or attempt + 1 == self.config.attempts:
                    raise exc from None
                self.report['action_retries'] += 1
                if exc.code in REGENERATE:
                    request_id = str(uuid.uuid4())
                time.sleep(min(self.config.retry_delay, max(0, self.left() - 2)))

    def context(self, turns_left):
        qa, ra = {}, {}
        query = query_from_facts(self.facts, audit=qa)
        cache_hit = bool(self.reference_cache and self.reference_cache[0] == query)
        if cache_hit:
            refs, ra = copy.deepcopy(self.reference_cache[1:])
            self.report['retrieval_cache_hits'] += 1
        else:
            refs = reference_packet(self.state.index, query, self.config.reference_chars, audit=ra)
            self.reference_cache = (query, copy.deepcopy(refs), copy.deepcopy(ra))
            self.report['retrieval_calls'] += 1
            self.report['empty_retrievals'] += int(not refs)
        # Trace identifiers, counts and reasons; no patient text, source body or secret in logs.
        self.report['query_selection'].append(qa)
        self.report['reference_packets'].append({k: v for k, v in ra.items() if k != 'excluded'} | {
            'cache_hit': cache_hit,
            'exclusion_counts': dict(collections.Counter(e['reason'] for e in ra['excluded'])),
            'delivered_units': [{'unit_id': r['unit_id'], 'evidence_ids': r['evidence_ids'], 'document_id': r['document_id'], 'body_chars': len(r['text'])} for r in refs]})
        current = visible_facts(self.facts, self.config.fact_chars)
        self.report['max_reference_chars'] = max(self.report['max_reference_chars'], len(json.dumps(refs, ensure_ascii=False)))
        value = {'current_patient_observations': current, 'observations_omitted': len(self.facts) - len(current),
            'reference_evidence': refs, 'reference_warning': 'NOT CURRENT PATIENT DATA. No reference fact may become an observed patient fact.',
            'doctor_explanations_already_sent': self.explanations,
            'explanation_warning': 'Successful SAY delivery only; understanding is unverified. Read the paired patient replies in observations.',
            'turns_left': turns_left,
            'recent_action_error_codes_not_patient_facts': self.report['errors'][-3:]}
        user = json.dumps(value, ensure_ascii=False)
        self.record_user = user
        self.report['max_prompt_chars'] = max(self.report['max_prompt_chars'], len(user))
        return user, current

    def action_context(self, baseline_user):
        if not self.features or not (self.clinical_plan or self.last_exam_failure):
            return baseline_user
        value = json.loads(baseline_user)
        if self.clinical_plan:
            value['clinical_plan_not_patient_facts'] = self.clinical_plan
        if self.last_exam_failure:
            value['last_exam_failure_not_patient_facts'] = self.last_exam_failure
        return json.dumps(value, ensure_ascii=False)

    def auxiliary(self, purpose, baseline_user, original, blocked, remaining):
        # Mark before every exit/call: timeout, malformed response or unavailable
        # budget never turns a once-only review into a retry loop.
        if purpose == 'PLAN':
            self.plan_attempted = True
        else:
            self.audit_attempted = True
        event = {'purpose': purpose, 'status': 'SKIPPED', 'http_attempts': 0}
        self.report['auxiliary_events'].append(event)
        if remaining < (2 if purpose == 'PLAN' else 1) or self.left() <= self.config.time_margin + 180:
            event['reason'] = 'TIME_OR_TURN_HEADROOM'
            return original
        before = self.report['doctor_http_attempts']
        try:
            # Independent audit: baseline factual context only, no planner text,
            # previous reasoning or unexecuted alternative passed as evidence.
            obj = parse_object(self.doctor(PLAN if purpose == 'PLAN' else AUDIT,
                                          baseline_user, purpose=purpose))
            if purpose == 'PLAN':
                text = plan_text(obj.get('plan'))
                if text is None:
                    raise ValueError('INVALID_CLINICAL_PLAN')
                self.clinical_plan = text
                event['status'] = 'PLAN_AVAILABLE'
                if 'next_action' not in obj:
                    return original
                if not isinstance(obj['next_action'], dict):
                    raise ValueError('INVALID_PLAN_ACTION')
                proposed = parse_action(obj['next_action'], blocked)
            else:
                proposed = audit_action(obj, blocked)
            event.update(status='ACCEPTED_PROPOSAL', action=proposed[0])
            return proposed
        except (ValueError, NovaError) as exc:
            if isinstance(exc, NovaError) and exc.code in CLOSED:
                raise
            event.update(status='FALLBACK_TO_ORIGINAL', reason=safe_error(exc.code) if isinstance(exc, NovaError) else 'INVALID_AUXILIARY_OUTPUT')
            return original
        finally:
            event['http_attempts'] = self.report['doctor_http_attempts'] - before

    def execute(self):
        session = self.session
        initial = session['initial']
        self.facts = [fact('F0', 'opening', observation_text(initial['opening'])), fact('F1', 'vitals', observation_text(initial['vital_signs']))]
        remaining = min(self.config.max_turns, max(0, int(session['turns_remaining'])))
        performed, rejected = set(), 0
        for _ in range(self.config.max_turns):
            if remaining <= 0 or self.left() <= self.config.time_margin or rejected >= 3:
                self.stop('TURN_LIMIT' if remaining <= 0 else 'TIME_MARGIN' if self.left() <= self.config.time_margin
                    else 'SERVER_REJECTION_LIMIT', 'EXPECTED_LIMIT' if rejected < 3 else 'EXECUTION_ERROR')
                break
            factual_user, _ = self.context(remaining)
            user = self.action_context(factual_user)
            base_user = user
            blocked = performed | (self.failed_exams if 'examination' in self.features else set())
            step = None
            chosen = {}
            for attempt in range(self.config.attempts):
                obj = None
                try:
                    obj = parse_object(self.doctor(self.step_prompt, user))
                    step = parse_action(obj, blocked)
                    chosen = obj
                    if 'examination' in self.features:
                        step, choice = examination_choice(obj, step, self.facts, blocked)
                        self.report['examination_choices'].append(choice)
                    self.report['action_sequence'].append({'event': 'MODEL_SELECTED', 'action': step[0],
                        'intent': step[2] if step[0] == 'SAY' else None, 'content_chars': len(step[1]),
                        'doctor_http_attempt': self.report['doctor_http_attempts']})
                    break
                except ValueError as exc:
                    self.reject(exc, 'ACTION')
                    if attempt + 1 < self.config.attempts:
                        suffix, audit = repair_request(exc, obj, attempt=attempt + 1)
                        self.report['action_repairs'].append(audit | {
                            'after_doctor_http_attempt': self.report['doctor_http_attempts']})
                        # Replace the previous repair. Keep observations and final-record base immutable.
                        user = base_user + suffix
                except NovaError as exc:
                    self.error(exc.code)
                    self.report['degraded'] = True
                    self.stop(safe_error(exc.code), 'EXPECTED_LIMIT' if exc.code in ('LOCAL_MODEL_BUDGET', 'LOCAL_SINGLE_PROMPT_BUDGET', 'LOCAL_FINAL_CONTEXT_BUDGET', 'LOCAL_DEADLINE') else 'EXECUTION_ERROR')
                    if exc.code in CLOSED:
                        raise
                    break
            if step is None:
                self.report['degraded'] = True
                if self.report['termination_reason'] is None:
                    self.stop('LOCAL_ACTION_FORMAT_RETRIES_EXHAUSTED', 'EXECUTION_ERROR')
                break
            if 'planner' in self.features:
                updated = plan_text(chosen.get('plan_update'))
                if updated is not None:
                    self.clinical_plan = updated
                if (not self.plan_attempted and self.report['actions_succeeded'] > 0 and step[0] != 'DONE'
                        and chosen.get('planning_ready') is True and chosen.get('urgent') is not True):
                    step = self.auxiliary('PLAN', factual_user, step, blocked, remaining)
            if step[0] == 'DONE' and 'audit' in self.features and not self.audit_attempted:
                step = self.auxiliary('AUDIT', factual_user, step, blocked, remaining)
            if step[0] == 'DONE':
                self.stop('DOCTOR_DONE', 'DOCTOR_DECISION')
                break
            action, content, intent = step
            try:
                reply = self.action(action, content=content)
                key = 'content' if action == 'SAY' else 'result'
                if not isinstance(reply, dict) or not isinstance(reply.get(key), str):
                    raise NovaError('MALFORMED_ACTION_REPLY')
                if reply.get('error') or reply.get('refused') or reply.get('status') in ('ERROR', 'REFUSED'):
                    raise NovaError('ACTION_NOT_ACKNOWLEDGED')
                turns = reply.get('turns_remaining', remaining - 1)
                if not isinstance(turns, int) or isinstance(turns, bool) or len(reply[key]) > 16000:
                    raise NovaError('MALFORMED_ACTION_REPLY')
                remaining = min(remaining - 1, max(0, turns))
                performed.add((action, content))
                self.report['actions_succeeded'] += 1
                self.report['action_counts'][action] = self.report['action_counts'].get(action, 0) + 1
                self.report['action_sequence'].append({'event': 'OBSERVATION_RECEIVED', 'action': action,
                    'observation_id': 'F' + str(len(self.facts)), 'action_number': len(performed)})
                if action == 'SAY' and intent == 'EXPLAIN':
                    self.explanations.append(content)
                observation = fact('F' + str(len(self.facts)), 'patient_reply' if action == 'SAY' else 'exam', reply[key], content)
                observation['consult_action_number'] = len(performed)
                observation['intent'] = intent if action == 'SAY' else 'EXAM'
                self.facts.append(observation)
                rejected = 0
            except NovaError as exc:
                self.error(exc.code)
                self.report['action_sequence'].append({'event': 'ACTION_FAILED', 'action': action, 'reason': safe_error(exc.code)})
                if exc.code in CLOSED:
                    raise
                if exc.code in TURN_REJECTIONS:
                    if action == 'EXAM' and self.features:
                        self.failed_exams.add((action, content))
                        self.last_exam_failure = {'content': content, 'reason': safe_error(exc.code)}
                    remaining -= 1
                    rejected += 1
                    continue
                self.report['degraded'] = True
                self.stop(safe_error(exc.code), 'EXECUTION_ERROR')
                break
        if self.report['termination_reason'] is None:
            self.stop('LOCAL_TURN_LIMIT', 'EXPECTED_LIMIT')
        user, current = self.context(remaining)
        note, diagnosis = None, None
        ready_for_record = True
        try:
            totals = self.budget.summary()
            available = (self.config.max_input_budget - totals['committed_input'],
                self.config.max_output_budget - totals['committed_output'],
                self.config.max_doctor_requests - totals['http_attempts'])
            self.record_envelope, packing = fit_record_envelope(user,
                min(self.config.attempts, self.config.max_doctor_requests), available, mode='FINAL')
            self.report['record_context_packing'].append(packing)
            user = self.record_envelope.base_user
        except NovaError as exc:
            self.error(exc.code)
            self.report['record_failure_reason'] = exc.code
            ready_for_record = False
        for _ in range(self.config.attempts):
            if not ready_for_record:
                break
            try:
                plan = parse_object(self.doctor(RECORD, user, final=True))
                note, diagnosis = render_record(plan, current, self.explanations)
                self.report['record_outcome'] = 'DOCTOR_RECORD_VALIDATED'
                break
            except ValueError as exc:
                self.reject(exc, 'RECORD')
                user += RECORD_REPAIR
            except NovaError as exc:
                self.error(exc.code)
                self.report['record_failure_reason'] = safe_error(exc.code)
                if exc.code in CLOSED:
                    raise
                break
        if note is None:
            note, diagnosis = fallback_record(visible_facts(self.facts, self.config.fact_chars), self.explanations)
            self.report['degraded'] = True
            self.report['record_outcome'] = 'LOCAL_OBSERVATION_ONLY_FALLBACK'
            self.report.setdefault('record_failure_reason', 'LOCAL_RECORD_FORMAT_RETRIES_EXHAUSTED')
        result = self.action('DIAGNOSE', note=note, diagnosis=diagnosis)
        self.report['action_sequence'].append({'event': 'SERVER_RESPONSE_RECEIVED', 'action': 'DIAGNOSE'})
        self.report.update(submitted=True, successful_execution=not self.report['degraded'] and self.report['doctor_successes'] > 0,
            observed_fact_count=len(self.facts), record_fields_valid=True, tests_action_count=0,
            diagnosis_unresolved=diagnosis == '진단 미정', duration_seconds=time.monotonic() - self.started)
        self.report.update(acknowledged_explanations=len(self.explanations),
                           patient_understanding_assessed=False)
        return result


def consult(client, state):
    # session is obtained via the exact SDK method. prepare state is ours, not a
    # guessed server session/state schema. Only fields used by official starter.
    session = client.session()
    run = Run(client, state, session)
    try:
        return run.execute()
    except NovaError as exc:
        run.error(exc.code)
        run.report.update(successful_execution=False, terminal_error=safe_error(exc.code))
        raise
    except (ValueError, KeyError, TypeError):
        run.report.update(successful_execution=False, terminal_error='INVALID_SESSION_OR_OBSERVATION')
        raise ValueError('INVALID_SESSION_OR_OBSERVATION') from None
