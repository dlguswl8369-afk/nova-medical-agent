import json
import hashlib
import collections
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


def prepare():
    path = os.environ.get('NOVA_RAG_INDEX', str(Path(__file__).resolve().parents[1] / 'indexes/bm25_ko.json.gz'))
    # No patient access, SDK call, network, or writable cache during prepare.
    return State(BM25Index.load(path))


class Run:
    def __init__(self, client, state, session):
        self.client, self.state, self.config, self.session = client, state, state.config, session
        self.facts, self.explanations = [], []
        self.report = {'model': MODEL, 'doctor_http_attempts': 0, 'doctor_unique_requests': 0, 'doctor_successes': 0,
            'input_budget_reserved': 0, 'output_budget_reserved': 0, 'reported_prompt_tokens': 0, 'reported_completion_tokens': 0,
            'usage_missing_responses': 0, 'action_attempts': 0, 'actions_succeeded': 0, 'invalid_model_outputs': 0,
            'errors': [], 'retrieval_calls': 0, 'empty_retrievals': 0, 'max_reference_chars': 0, 'max_prompt_chars': 0,
            'reference_packets': [], 'query_selection': [], 'action_counts': {}, 'model_retries': 0, 'action_retries': 0,
            'submitted': False, 'degraded': False, 'diagnosis_accuracy_evaluated': False, 'clinical_record_quality_evaluated': False}
        state.report = self.report
        self.budget = Budget(self.config.max_input_budget, self.config.max_output_budget, self.config.max_doctor_requests)
        self.report.update(rejection_events=[], action_sequence=[], final_http_attempts=0,
            termination_reason=None, termination_kind=None, record_outcome=None,
            pre_call_input_estimates_sum=0, pre_call_output_caps_sum=0)
        self.sync_budget()
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

    def doctor(self, system, user, final=False):
        cfg, report = self.config, self.report
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
        limit = 4096 if final else 2048
        # UTF-8 bytes + structural allowance conservatively bound byte-BPE tokens.
        charge = len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 1024
        if charge > 100000:
            raise NovaError('LOCAL_SINGLE_PROMPT_BUDGET')
        # Keep room for up to three final-record transmissions/new generations,
        # each at the official maximum input, plus its unchanged output cap.
        # This is headroom, NOT charged usage. Actual usage frees reservations.
        headroom = (0, 0, 0) if final else (cfg.attempts * 100000, cfg.attempts * 4096, cfg.attempts)
        request_id = str(uuid.uuid4())
        fingerprint = hashlib.sha256(json.dumps([messages, limit, MODEL, 'medium'], ensure_ascii=False).encode()).hexdigest()
        for attempt in range(cfg.attempts):
            if self.left() <= 10:
                raise NovaError('LOCAL_DEADLINE')
            if final and report['final_http_attempts'] >= cfg.attempts:
                raise NovaError('LOCAL_FINAL_RETRY_BUDGET')
            try:
                self.budget.reserve(request_id, charge, limit, fingerprint, headroom=headroom,
                    phase='RECORD' if final else 'ACTION')
            finally:
                self.sync_budget()
            report['final_http_attempts'] += int(final)
            report['pre_call_input_estimates_sum'] += charge
            report['pre_call_output_caps_sum'] += limit
            # Avoid starting a 240-second request near the session deadline.
            if hasattr(self.client, 'timeout'):
                self.client.timeout = max(1, min(240, self.left() - 5))
            try:
                response = self.client.chat(messages, max_tokens=limit, reasoning_effort='medium', model=MODEL, request_id=request_id)
                report['doctor_successes'] += 1
                self.budget.settle(request_id, response.get('usage') if isinstance(response, dict) else None)
                self.sync_budget()
                return response['choices'][0]['message']['content']
            except (NovaError, TimeoutError, OSError) as exc:
                if not isinstance(exc, NovaError):
                    exc = NovaError('API_UNAVAILABLE')
                self.error(exc.code)
                if exc.code not in TRANSIENT or attempt + 1 == cfg.attempts:
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
        refs = reference_packet(self.state.index, query, self.config.reference_chars, audit=ra)
        # Trace identifiers, counts and reasons; no patient text, source body or secret in logs.
        self.report['query_selection'].append(qa)
        self.report['reference_packets'].append({k: v for k, v in ra.items() if k != 'excluded'} | {
            'exclusion_counts': dict(collections.Counter(e['reason'] for e in ra['excluded'])),
            'delivered_units': [{'unit_id': r['unit_id'], 'evidence_ids': r['evidence_ids'], 'document_id': r['document_id'], 'body_chars': len(r['text'])} for r in refs]})
        current = visible_facts(self.facts, self.config.fact_chars)
        self.report['retrieval_calls'] += 1
        self.report['empty_retrievals'] += int(not refs)
        self.report['max_reference_chars'] = max(self.report['max_reference_chars'], len(json.dumps(refs, ensure_ascii=False)))
        value = {'current_patient_observations': current, 'observations_omitted': len(self.facts) - len(current),
            'reference_evidence': refs, 'reference_warning': 'NOT CURRENT PATIENT DATA. No reference fact may become an observed patient fact.',
            'doctor_explanations_already_sent': self.explanations, 'turns_left': turns_left,
            'recent_action_error_codes_not_patient_facts': self.report['errors'][-3:]}
        user = json.dumps(value, ensure_ascii=False)
        self.report['max_prompt_chars'] = max(self.report['max_prompt_chars'], len(user))
        return user, current

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
            user, _ = self.context(remaining)
            step = None
            for attempt in range(self.config.attempts):
                try:
                    obj = parse_object(self.doctor(STEP, user))
                    step = parse_action(obj, performed)
                    self.report['action_sequence'].append({'event': 'MODEL_SELECTED', 'action': step[0],
                        'intent': step[2] if step[0] == 'SAY' else None, 'content_chars': len(step[1]),
                        'doctor_http_attempt': self.report['doctor_http_attempts']})
                    break
                except ValueError as exc:
                    self.reject(exc, 'ACTION')
                    user += '\n형식 오류입니다. TEST 금지, SAY/EXAM 1~30자, 질문/동작 하나, 반복 금지. JSON 하나만 다시 출력하세요.'
                except NovaError as exc:
                    self.error(exc.code)
                    self.report['degraded'] = True
                    self.stop(safe_error(exc.code), 'EXPECTED_LIMIT' if exc.code in ('LOCAL_MODEL_BUDGET', 'LOCAL_SINGLE_PROMPT_BUDGET', 'LOCAL_DEADLINE') else 'EXECUTION_ERROR')
                    if exc.code in CLOSED:
                        raise
                    break
            if step is None:
                self.report['degraded'] = True
                if self.report['termination_reason'] is None:
                    self.stop('LOCAL_ACTION_FORMAT_RETRIES_EXHAUSTED', 'EXECUTION_ERROR')
                break
            if step[0] == 'DONE':
                self.stop('DOCTOR_DONE', 'DOCTOR_DECISION')
                break
            action, content, intent = step
            try:
                reply = self.action(action, content=content)
                key = 'content' if action == 'SAY' else 'result'
                if not isinstance(reply, dict) or not isinstance(reply.get(key), str):
                    raise NovaError('MALFORMED_ACTION_REPLY')
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
                    remaining -= 1
                    rejected += 1
                    performed.add((action, content))
                    continue
                self.report['degraded'] = True
                self.stop(safe_error(exc.code), 'EXECUTION_ERROR')
                break
        if self.report['termination_reason'] is None:
            self.stop('LOCAL_TURN_LIMIT', 'EXPECTED_LIMIT')
        user, current = self.context(remaining)
        note, diagnosis = None, None
        for _ in range(self.config.attempts):
            try:
                plan = parse_object(self.doctor(RECORD, user, final=True))
                note, diagnosis = render_record(plan, current, self.explanations)
                self.report['record_outcome'] = 'DOCTOR_RECORD_VALIDATED'
                break
            except ValueError as exc:
                self.reject(exc, 'RECORD')
                user += '\n기록 형식 또는 근거 ID 오류입니다. 실제 관찰 ID만 선택하고 예선 O.tests는 비우세요. source_refs에는 ID 목록만 씁니다.'
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
