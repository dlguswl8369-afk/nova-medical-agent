"""Read-only context projections, not new consultations or clinical scoring."""
import copy
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_batch import ROOT, load_harness, policy
from package_batch import save


def main():
    out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=False)
    # Optional prior comparison: after a RAG-only change, reuse unaffected
    # context projections and refresh only V1/V4 search packets.
    previous = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')) if len(sys.argv) > 2 else None
    harness = ROOT.parent / 'nova-medical-agent-harness'
    h = load_harness(harness); before = policy(h)
    sys.path[:0] = [str(ROOT / 'app'), str(harness / 'scripts')]
    from clinical_review import load_sources, historical_run, pointer
    from nova_agent.context import fact, observation_text
    from nova_agent.loop import Run, State
    from nova_agent.experiments import FLAGS
    from nova_retrieval import BM25Index
    from nova_retrieval.guidelines import GuidelinesIndex, CombinedIndex
    sys.addaudithook(lambda event, args: h.guard_event(event, args, out))
    catalog = json.loads((harness / 'harness/cases/clinical_review.json').read_text(encoding='utf-8'))
    docs, checks = load_sources(catalog, ROOT.parent, harness)
    assert all(c['status'] == 'PASS' for c in checks.values()), 'PINNED_SOURCE_REQUIRED'
    class EmptyIndex:
        def search(self, *args, **kwargs): return []
    def decode(view):
        table = view['current_patient_observations']
        if isinstance(table, list): return table
        return [dict((table['columns'][i], row[i]) for i in present)
                for row, present in zip(table['rows'], table['present'])]
    def project(facts, index, strategy):
        r = Run(None, State(index, strategy=strategy), {})
        r.facts = copy.deepcopy(facts)
        r.explanations = [f['question'] for f in facts if f.get('intent') == 'EXPLAIN']
        start = time.perf_counter()
        user, _ = r.context(10)
        elapsed = time.perf_counter() - start
        view = json.loads(user)
        return r, view, {'input_bytes': len(user.encode()) + len(r.step_prompt.encode()),
                         'user_bytes': len(user.encode()), 'step_bytes': len(r.step_prompt.encode()),
                         'local_projection_ms': round(elapsed * 1000, 2)}
    case_rows = previous['cases'] if previous else []
    for case in ([] if previous else catalog['cases']):
        source = docs[case['run_source']]
        if case['provenance']['kind'] == 'development_log':
            facts = historical_run(source)['observations']
        else:
            source = pointer(source, case['run_pointer']) if case.get('run_pointer') else source
            initial = source.get('doctor_input', {})
            facts = [fact('F0', 'opening', observation_text(initial.get('opening', ''))),
                     fact('F1', 'vitals', observation_text(initial.get('vital_signs', '')))]
            for event in source.get('trace', []):
                if event.get('acknowledged') is True and event['action'] in ('SAY', 'EXAM'):
                    f = fact('F' + str(len(facts)), 'exam' if event['action'] == 'EXAM' else 'patient_reply',
                             observation_text(event['response']), event['content'])
                    if event.get('intent'): f['intent'] = event['intent']
                    facts.append(f)
        variants, baseline = {}, None
        for version in FLAGS:
            run, view, metrics = project(facts, EmptyIndex(), version)
            pairs = sorted(decode(view), key=lambda f: f['id'])
            if version == 'V0': baseline = (pairs, run.record_user, metrics['input_bytes'])
            assert pairs == baseline[0] and run.record_user == baseline[1]
            # Strict lossless projection is the leakage check: no evaluator-only
            # script, hidden examination or reference-note field is accepted.
            assert all(f in facts for f in pairs)
            variants[version] = metrics | {'baseline_input_byte_delta': metrics['input_bytes'] - baseline[2],
                                          'visible_ids': [f['id'] for f in decode(view)],
                                          'omitted': view['observations_omitted'], 'automatic_preservation': 'PASS'}
        case_rows.append({'case_id': case['id'], 'provenance': case['provenance'],
                          'variants': variants, 'clinical_appropriateness': 'REVIEW',
                          'new_model_behavior': 'NOT_EVALUATED', 'human_review': case['human_review']})
    legacy = BM25Index.load(ROOT / 'app/indexes/bm25_ko.json.gz')
    guide = GuidelinesIndex(ROOT / 'app/indexes/guidelines.sqlite',
                            ROOT.parent / 'nova_extension_work_20261015/inputs/guidelines')
    packets = []
    try:
        for case_id in ('C01', 'C10', 'C03'):
            initial = docs[case_id + '-public']['start_information']
            facts = [fact('F0', 'opening', observation_text(initial['opening'])),
                     fact('F1', 'vitals', observation_text(initial['vital_signs']))]
            for backend, index in (('legacy', legacy), ('legacy+guidelines', CombinedIndex(legacy, guide))):
                baseline, variants = None, {}
                if previous:
                    old = next(p for p in previous['search_packets'] if p['public_initial_only'] == case_id and p['backend'] == backend)
                    variants = copy.deepcopy(old['variants'])
                for version in (('V1', 'V4') if previous else FLAGS):
                    run, view, metrics = project(facts, index, version)
                    refs = view['reference_evidence']
                    if previous:
                        baseline = (json.loads(run.record_user)['reference_evidence'], run.record_user, variants['V0']['input_bytes'])
                        assert [r['unit_id'] for r in baseline[0]] == [r['unit_id'] for r in variants['V0']['units']]
                    if version == 'V0': baseline = (refs, run.record_user, metrics['input_bytes'])
                    assert all(row in refs for row in baseline[0]), 'BASELINE_EVIDENCE_LOSS'
                    assert run.record_user == baseline[1], 'RECORD_CHANGE'
                    assert len(json.dumps(refs, ensure_ascii=False)) <= run.config.reference_chars
                    variants[version] = metrics | {
                        'baseline_input_byte_delta': metrics['input_bytes'] - baseline[2],
                        'units': [{k: r.get(k) for k in ('unit_id', 'source_role', 'text_scope', 'source_sha256')} for r in refs],
                        'packet_chars': len(json.dumps(refs, ensure_ascii=False)),
                        'selection': run.report['experiment_packets'][-1] if run.report['experiment_packets'] else {'status': 'BASELINE'},
                        'baseline_units_preserved': 'PASS'}
                packets.append({'public_initial_only': case_id, 'backend': backend, 'variants': variants})
    finally:
        guide.close()
    save(out / 'comparison.json', {'status': 'PASS', 'clinical_quality': 'REVIEW', 'new_model_runs': 0,
                                  'source_integrity': checks, 'cases': case_rows, 'search_packets': packets,
                                  'unchanged_projections_reused_from': str(Path(sys.argv[2]).resolve()) if previous else None,
                                  'scope': '10 existing trace projections and 3 public openings; no new actions generated',
                                  'baseline_commit': before['baseline_commit']})
    print(json.dumps({'status': 'PASS', 'case_projections': len(case_rows) * 5,
                      'search_projections': len(packets) * 5, 'clinical': 'REVIEW'}))


if __name__ == '__main__':
    main()
