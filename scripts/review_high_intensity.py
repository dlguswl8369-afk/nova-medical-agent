"""Project existing reviewed observations into candidate contexts; no new actions."""
import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_high_intensity import ROOT, load_harness, policy
from package_high_intensity import save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.is_relative_to(ROOT):
        raise ValueError('REVIEW_OUTPUT_MUST_BE_OUTSIDE_GIT_WORKTREE')
    out.mkdir(parents=True, exist_ok=False)
    harness = ROOT.parent / 'nova-medical-agent-harness'
    h = load_harness(harness)
    before = policy(h)
    sys.path[:0] = [str(ROOT / 'app'), str(harness / 'scripts')]
    sys.addaudithook(lambda event, params: h.guard_event(event, params, out))
    from clinical_review import load_sources, historical_run, pointer
    from nova_agent.context import fact, observation_text
    from nova_agent.loop import Run, State
    from nova_agent.clinical_strategy import FEATURES, PLAN, AUDIT, call_settings
    from nova_agent.record_budget import input_charge

    catalog = json.loads((harness / 'harness/cases/clinical_review.json').read_text(encoding='utf-8'))
    docs, source_checks = load_sources(catalog, ROOT.parent, harness)
    assert all(item['status'] == 'PASS' for item in source_checks.values()), 'PINNED_SOURCE_REQUIRED'

    class EmptyIndex:
        def search(self, *args, **kwargs):
            return []

    rows = []
    probe = 'SYNTHETIC_PLAN_PROJECTION_NOT_A_FACT'
    for case in catalog['cases']:
        source = docs[case['run_source']]
        if case['provenance']['kind'] == 'development_log':
            observed = historical_run(source)
            facts = observed['observations']
            source_scope = observed['trace_scope']
            trace_complete = observed['trace_complete']
        else:
            source = pointer(source, case['run_pointer']) if case.get('run_pointer') else source
            initial = source.get('doctor_input', {})
            facts = [fact('F0', 'opening', observation_text(initial.get('opening', ''))),
                     fact('F1', 'vitals', observation_text(initial.get('vital_signs', '')))]
            for event in source.get('trace', []):
                if event.get('acknowledged') is True and event['action'] in ('SAY', 'EXAM'):
                    item = fact('F' + str(len(facts)),
                                'exam' if event['action'] == 'EXAM' else 'patient_reply',
                                observation_text(event['response']), event['content'])
                    if event.get('intent'):
                        item['intent'] = event['intent']
                    facts.append(item)
            source_scope = 'Synthetic fixture; acknowledged trace items only'
            trace_complete = source.get('trace_complete') is True
        variants, baseline = {}, None
        for strategy, enabled in FEATURES.items():
            run = Run(None, State(EmptyIndex(), strategy=strategy), {})
            run.facts = copy.deepcopy(facts)
            run.explanations = [f['question'] for f in facts if f.get('intent') == 'EXPLAIN']
            user, current = run.context(10)
            action = run.action_context(user)
            view = json.loads(action)
            measured_bytes = len(action.encode()) + len(run.step_prompt.encode())
            if strategy == 'BASELINE':
                baseline = (view, run.record_user, measured_bytes)
            assert view == baseline[0] and run.record_user == baseline[1]
            assert all(f in facts for f in current)
            assert view['reference_evidence'] == []
            assert run.report['doctor_http_attempts'] == run.report['actions_succeeded'] == 0
            variant = {'automatic_context_preservation': 'PASS',
                       'visible_ids': [f['id'] for f in current],
                       'observations_omitted': view['observations_omitted'],
                       'action_input_bytes': measured_bytes,
                       'action_input_byte_delta': measured_bytes - baseline[2],
                       'action_input_charge': input_charge(run.step_prompt, action),
                       'step_bytes': len(run.step_prompt.encode()), 'user_bytes': len(action.encode()),
                       'auxiliary_payloads': {}}
            for purpose, prompt, feature in (('PLAN', PLAN, 'planner'), ('AUDIT', AUDIT, 'audit')):
                if feature in enabled:
                    cap, effort = call_settings(strategy, purpose, 480)
                    assert probe not in user
                    variant['auxiliary_payloads'][purpose] = {
                        'input_bytes': len(prompt.encode()) + len(user.encode()),
                        'input_charge': input_charge(prompt, user),
                        'output_cap_including_reasoning': cap, 'reasoning_effort': effort,
                        'no_model_call': True, 'context': 'unchanged factual context; no plan text'}
                    if strategy == 'H4' and purpose == 'AUDIT':
                        low_cap, low_effort = call_settings(strategy, purpose, 200)
                        variant['auxiliary_payloads'][purpose]['lower_time_headroom'] = {
                            'output_cap_including_reasoning': low_cap, 'reasoning_effort': low_effort}
            if 'planner' in enabled:
                run.clinical_plan = probe
                with_plan = run.action_context(user)
                projected = json.loads(with_plan)
                assert projected.pop('clinical_plan_not_patient_facts') == probe
                assert projected == baseline[0] and run.record_user == baseline[1]
                assert probe not in json.dumps(current, ensure_ascii=False)
                variant['separate_plan_probe'] = {
                    'status': 'PASS', 'probe_chars': len(probe),
                    'action_byte_addition': len(with_plan.encode()) - len(action.encode()),
                    'record_and_observations_unchanged': True,
                    'meaning': 'synthetic label checks separation, not a generated clinical plan'}
            variants[strategy] = variant
        rows.append({'case_id': case['id'], 'provenance': case['provenance'],
                     'run_source': case['run_source'], 'source_trace_scope': source_scope,
                     'source_trace_complete': trace_complete, 'variants': variants,
                     'clinical_appropriateness': 'REVIEW', 'new_clinical_performance': 'NOT_EVALUATED'})

    after = {p.relative_to(ROOT).as_posix(): 'SYMLINK' if p.is_symlink() else h.blob_hash(p)
             for p in (ROOT / 'app').rglob('*') if (p.is_file() or p.is_symlink()) and '__pycache__' not in p.parts}
    assert after == before['app_snapshot'], 'APP_CHANGED_DURING_READ_ONLY_PROJECTION'
    totals = {'cases': len(rows), 'projections': sum(len(r['variants']) for r in rows),
              'source_files_verified': len(source_checks), 'real_api_calls': 0, 'new_sessions': 0,
              'new_actions': 0, 'maximum_omitted_observations': max(v['observations_omitted']
                  for r in rows for v in r['variants'].values())}
    deltas = {strategy: sorted({r['variants'][strategy]['action_input_byte_delta'] for r in rows})
              for strategy in FEATURES}
    save(out / 'review.json', {'status': 'PASS', 'clinical_appropriateness': 'REVIEW',
         'new_clinical_performance': 'NOT_EVALUATED', 'baseline_commit': before['baseline_commit'],
         'harness_commit': before['harness_commit'], 'totals': totals,
         'action_input_byte_deltas_no_plan': deltas, 'source_integrity': source_checks, 'cases': rows,
         'limitations': ['Only existing successful/acknowledged observations were projected.',
                        'No new plan, audit decision, clinical action or model output was generated.',
                        'Byte measurements are not observed tokens, cost, latency or clinical quality.',
                        'The baseline visible-fact cap remains; longer future traces can omit observations.',
                        'Patient scripts, exam result tables and reference notes stay reviewer-only.']})
    print(json.dumps({'status': 'PASS', **totals, 'clinical_appropriateness': 'REVIEW',
                      'new_clinical_performance': 'NOT_EVALUATED', 'action_byte_deltas': deltas}))


if __name__ == '__main__':
    main()
