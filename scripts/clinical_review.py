"""Read-only, model-free evidence review. No clinical scoring or app imports."""
import copy
import hashlib
import json
from pathlib import Path
import unicodedata


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pointer(document, path):
    if not path.startswith('/'):
        raise ValueError('JSON_POINTER_REQUIRED')
    for part in path[1:].split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        document = document[int(key)] if isinstance(document, list) else document[key]
    return document


def load_sources(catalog, workspace, repo):
    """Only pinned local files; missing data never falls back to a different version."""
    documents, checks = {}, {}
    for sid, spec in catalog['sources'].items():
        base = (repo if spec['root'] == 'repo' else workspace).resolve()
        path = (base / spec['path']).resolve()
        check = {'path': spec['path'], 'kind': spec['kind'], 'version': spec.get('version'),
                 'sha256': spec['sha256']}
        try:
            if not path.is_relative_to(base):
                raise ValueError('SOURCE_OUTSIDE_ROOT')
            raw = path.read_bytes()
            if digest(raw) != spec['sha256']:
                raise ValueError('SOURCE_HASH_MISMATCH')
            documents[sid] = json.loads(raw)
            check.update(status='PASS', reason='Pinned source bytes verified; not clinical validation')
        except OSError:
            check.update(status='NOT_EVALUATED', reason='Local source unavailable')
        except (ValueError, TypeError):
            check.update(status='FAIL', reason='Source hash, path or JSON invalid')
        checks[sid] = check
    return documents, checks


def historical_run(raw):
    """Join only SDK OK responses to matching observation turn/question/text.

    The preserved events cover successful SDK actions, not all generated actions.
    DONE is an internal termination reason, never invented as an SDK event.
    """
    observations = raw.get('last_reference_context', {}).get('current_patient_observations', [])
    trace, accepted = [], [copy.deepcopy(o) for o in observations if o['kind'] in {'opening', 'vitals'}]
    for n, event in enumerate(raw.get('events', []), 1):
        reply = event.get('response', {})
        ok = reply.get('status') == 'OK' and event['action'] in {'SAY', 'EXAM'}
        reply_text = reply.get('result') if event['action'] == 'EXAM' else reply.get('content')
        matched = [o for o in observations if ok and o.get('consult_action_number') == reply.get('turn')
                   and o.get('question') == event.get('content') and o.get('text') == reply_text
                   and o['kind'] == ('exam' if event['action'] == 'EXAM' else 'patient_reply')]
        intent = matched[0].get('intent') if len(matched) == 1 else None
        accepted.extend(copy.deepcopy(matched))
        trace.append({'id': f'E{n}', 'action': event['action'], 'intent': intent,
                      'content': event.get('content'), 'response': reply_text,
                      'acknowledged': ok, 'observation_ids': [o['id'] for o in matched]})
    report = raw.get('report', {})
    complete = (isinstance(raw.get('events'), list) and isinstance(report.get('actions_succeeded'), int)
                and sum(t['acknowledged'] for t in trace) == report['actions_succeeded'])
    context = raw.get('last_reference_context', {})
    forbidden = {'evaluator_only', 'patient_script', 'exam_results', 'reference_record', 'model_record'}
    def forbidden_key(value):
        if isinstance(value, dict):
            return bool(forbidden.intersection(value)) or any(forbidden_key(v) for v in value.values())
        return isinstance(value, list) and any(forbidden_key(v) for v in value)
    captured = doctor_view({'observations': observations})
    if forbidden_key(context):
        captured['evaluator_only_detected'] = True
    return {'trace': trace, 'observations': accepted, 'captured_doctor_view': captured,
            'final_record': raw.get('final', {}).get('note', {}),
            'trace_complete': complete, 'trace_scope': 'successful SDK actions; rejected attempts not reconstructed',
            'termination': report.get('termination_reason'), 'record_outcome': report.get('record_outcome'),
            'server_status': next((e.get('response', {}).get('status') for e in reversed(raw.get('events', []))
                                   if e['action'] == 'DIAGNOSE'), None)}


def synthetic_run(case):
    return {'trace': copy.deepcopy(case.get('trace', [])), 'observations': [],
            'initial': copy.deepcopy(case.get('doctor_input', {})),
            'final_record': copy.deepcopy(case.get('final_record', {})),
            'trace_complete': case.get('trace_complete') is True, 'trace_scope': 'synthetic fixture only'}


def doctor_view(run):
    """Inspection projection only; evaluator scripts/results/reference notes are never inputs.

    Synthetic initial input supplies opening/vitals only, never arbitrary observations.
    Historical observations require a successful event join except initial opening/vitals.
    """
    facts = run.get('observations', [])
    initial = run.get('initial', {})
    view = {'opening': initial.get('opening', ''), 'vital_signs': initial.get('vital_signs', ''), 'observations': []}
    for o in facts:
        if o['kind'] in {'opening', 'vitals'}:
            view['opening' if o['kind'] == 'opening' else 'vital_signs'] = o['text']
        else:
            view['observations'].append({k: o[k] for k in ('id', 'kind', 'text', 'question', 'intent') if k in o})
    return view


def check_doctor_view(view, run):
    # Exact data equality also rejects injected evaluator fields, forged IDs and changed text.
    return {'status': 'PASS' if view == doctor_view(run) else 'FAIL',
            'reason': 'Allowlisted projection of initial input and SDK-linked observations only; not all future prompts'}


def leaves(value, path=''):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, path + '/' + k.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for n, v in enumerate(value):
            yield from leaves(v, path + '/' + str(n))
    elif isinstance(value, str) and value.strip():
        yield path, value


def analyze_run(run):
    """Report narrow execution facts; all clinical adequacy stays REVIEW/NOT_EVALUATED."""
    trace = run['trace']
    record = list(leaves(run['final_record']))
    successful = [t for t in trace if t.get('acknowledged') is True]
    explanations = [t for t in successful if t.get('action') == 'SAY' and t.get('intent') == 'EXPLAIN']
    inventory = {key: [t['id'] for t in successful if t.get('action') == action and (intent is None or t.get('intent') == intent)]
                 for key, action, intent in [('asked', 'SAY', 'ASK'), ('examined', 'EXAM', None), ('explained', 'SAY', 'EXPLAIN')]}
    inventory['unclassified_say'] = [t['id'] for t in successful if t.get('action') == 'SAY' and t.get('intent') not in {'ASK', 'EXPLAIN'}]
    pairs, repeated, seen = [], [], {}
    for t in successful:
        if t.get('action') not in {'SAY', 'EXAM'} or not isinstance(t.get('content'), str):
            continue
        paths = [p for p, text in record if t['content'] in text and isinstance(t.get('response'), str)
                 and t['response'].strip() and t['response'] in text]
        pairs.append({'trace_id': t['id'], 'observation_ids': t.get('observation_ids', []),
                      'literal_question_response_record_paths': paths,
                      'status': 'PASS' if paths else 'REVIEW' if record else 'NOT_EVALUATED',
                      'reason': 'Literal pair preservation only; absence of exact wording is not proof of omission'})
        key = (t['action'], t.get('intent'), unicodedata.normalize('NFC', t['content']))
        if key in seen:
            repeated.append({'trace_ids': [seen[key], t['id']], 'status': 'REVIEW',
                             'reason': 'Identical wording; clarification, prior unknown reply and clinical need require review'})
        seen[key] = t['id']
    plans = []
    for path, text in record:
        if not path.startswith('/P/'):
            continue
        matches = [t['id'] for t in explanations if isinstance(t.get('content'), str) and t['content'].strip() and t['content'] in text]
        plans.append({'record_pointer': path, 'literal_explanation_ids': matches,
                      'status': 'REVIEW' if trace else 'NOT_EVALUATED',
                      'reason': 'P is a record, not delivery. Matches cover only that sentence, never the whole field; nonmatch needs semantic review'})
    return {'execution': {'status': 'PASS' if trace else 'NOT_EVALUATED', 'ids': inventory,
                          'absence_established': run['trace_complete'], 'scope': run['trace_scope'],
                          'reason': 'Extraction of logged actions only; missing/incomplete trace cannot establish absence'},
            'record_pairs': pairs, 'plan_vs_delivery': plans, 'exact_repeats': repeated,
            'understanding': {'status': 'REVIEW' if explanations else 'NOT_EVALUATED',
                              'evidence': [t['id'] for t in explanations], 'reason': 'SDK OK and assent do not establish understanding'},
            'clinical_adequacy': 'REVIEW' if trace else 'NOT_EVALUATED',
            'termination': run.get('termination'), 'server_status': run.get('server_status'),
            'record_outcome': run.get('record_outcome'),
            'evaluator_separation': check_doctor_view(run['captured_doctor_view'], run) if 'captured_doctor_view' in run else
            {'status': 'NOT_EVALUATED', 'reason': 'No captured historical Doctor context; projection covered by isolated tests'}}


def evaluate(catalog, workspace, repo, show_evidence=False, decisions=None):
    docs, checks = load_sources(catalog, workspace, repo)
    if catalog.get('schema_version') != 2:
        raise ValueError('REVIEW_CATALOG_VERSION')
    # Metadata is a separate pinned source, not inferred from filenames or current HEAD.
    for sid, spec in catalog['sources'].items():
        if spec['kind'] == 'development_log' and sid in docs:
            meta = docs.get(spec['metadata_source'])
            if meta is None or meta.get('version') != spec['version'] or meta.get('case') != spec['public_case']:
                checks[sid].update(status='NOT_EVALUATED' if meta is None else 'FAIL', reason='Version provenance not established')
                del docs[sid]
    runs = {}
    for sid, spec in catalog['sources'].items():
        if sid in docs and spec['kind'] in {'development_log', 'synthetic_example'}:
            runs[sid] = historical_run(docs[sid]) if spec['kind'] == 'development_log' else synthetic_run(docs[sid])
    rows = []
    ids = set()
    for case in catalog['cases']:
        if case['id'] in ids or not all(case.get(k) for k in ('applicability', 'expected_range', 'forbidden_errors', 'human_review', 'evidence')):
            raise ValueError('CASE_CONTEXT_OR_UNIQUE_ID_REQUIRED')
        ids.add(case['id'])
        evidence = []
        for ref in case['evidence']:
            item = dict(ref)
            try:
                source = docs[ref['source']]
                value = pointer(source, ref['pointer'])
                if ref.get('id') and (not isinstance(value, dict) or value.get('id') != ref['id']):
                    raise ValueError('EVIDENCE_ID_MISMATCH')
                item['status'] = 'PASS' if value is not None and value != '' and value != [] and value != {} else 'NOT_EVALUATED'
                item['value_sha256'] = digest(json.dumps(value, ensure_ascii=False, sort_keys=True).encode())
                if show_evidence:
                    item['original_value'] = value  # stdout-only, opt-in reviewer view; never Doctor input
            except KeyError:
                item['status'] = 'NOT_EVALUATED' if ref['source'] not in docs else 'FAIL'
            except (IndexError, TypeError, ValueError):
                item['status'] = 'FAIL'
            evidence.append(item)
        run = runs.get(case.get('run_source'))
        if case.get('run_pointer') and case.get('run_source') in docs:
            run = synthetic_run(pointer(docs[case['run_source']], case['run_pointer']))
        row = {k: case[k] for k in ('id', 'domain', 'provenance', 'applicability', 'expected_range', 'forbidden_errors', 'human_review')}
        row.update(evidence=evidence,
                   status='REVIEW' if all(e['status'] == 'PASS' for e in evidence) and run else 'NOT_EVALUATED',
                   reason='Clinical appropriateness is a human decision; no automatic score',
                   execution=analyze_run(run) if run else {'status': 'NOT_EVALUATED', 'reason': 'No execution trace'})
        rows.append(row)
    # Optional human decisions are attributed; no status can be promoted without verified references.
    decided = set()
    for decision in decisions or []:
        row = next((r for r in rows if r['id'] == decision.get('case_id')), None)
        if row is None or row['id'] in decided or not all(decision.get(k) for k in ('reviewer', 'reviewed_at', 'reason', 'evidence')):
            raise ValueError('ATTRIBUTED_UNIQUE_REVIEW_REQUIRED')
        verified = {(e['source'], e['pointer']) for e in row['evidence'] if e['status'] == 'PASS'}
        if decision.get('status') not in {'PASS', 'FAIL', 'REVIEW', 'NOT_EVALUATED'} or not all(
                (e['source'], e['pointer']) in verified for e in decision['evidence']):
            raise ValueError('VERIFIED_REVIEW_EVIDENCE_REQUIRED')
        if decision['status'] != 'NOT_EVALUATED' and row['status'] == 'NOT_EVALUATED':
            raise ValueError('INCOMPLETE_EVIDENCE_CANNOT_PASS')
        row.update(status=decision['status'], human_decision=decision)
        decided.add(row['id'])
    summaries = {sid: analyze_run(run) for sid, run in runs.items()}
    failure = (any(c['status'] == 'FAIL' for c in checks.values())
               or any(e['status'] == 'FAIL' for r in rows for e in r['evidence'])
               or any(r['evaluator_separation']['status'] == 'FAIL' for r in summaries.values()))
    return {'status': 'FAIL' if failure else 'REVIEW', 'sources': checks,
            'historical_runs': summaries, 'cases': rows,
            'clinical_score': 'NOT_EVALUATED', 'website_detail_logs': 'NOT_EVALUATED', 'real_api_calls': 0,
            'reason': 'Evidence integrity and execution facts only; human judgments are separately attributed'}
