"""Evidence mechanics only. No assertion of clinical correctness or score gains."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from clinical_review import analyze_run, check_doctor_view, digest, doctor_view, evaluate, historical_run, load_sources, synthetic_run


class ClinicalReviewTests(unittest.TestCase):
    def raw(self, ok=True):
        return {'events': [{'action': 'SAY', 'content': '추가 확인이 필요해요.',
                            'response': {'status': 'OK' if ok else 'ERROR', 'turn': 1, 'content': '네'}}],
                'last_reference_context': {'current_patient_observations': [
                    {'id': 'F0', 'kind': 'opening', 'text': '불편해요.'},
                    {'id': 'F2', 'kind': 'patient_reply', 'question': '추가 확인이 필요해요.',
                     'text': '네', 'consult_action_number': 1, 'intent': 'EXPLAIN'}]},
                'final': {'note': {'P': {'education': '추가 확인이 필요해요. 다음 주 재진.'}}},
                'report': {'actions_succeeded': 1, 'termination_reason': 'LOCAL_ACTION_FORMAT_RETRIES_EXHAUSTED'}}

    def test_successful_delivery_does_not_establish_understanding_or_whole_plan(self):
        result = analyze_run(historical_run(self.raw()))
        self.assertEqual(result['execution']['ids']['explained'], ['E1'])
        self.assertEqual(result['plan_vs_delivery'][0]['literal_explanation_ids'], ['E1'])
        self.assertEqual(result['plan_vs_delivery'][0]['status'], 'REVIEW')
        self.assertEqual(result['understanding']['status'], 'REVIEW')
        self.assertEqual(result['termination'], 'LOCAL_ACTION_FORMAT_RETRIES_EXHAUSTED')

    def test_failed_or_unmatched_response_is_not_delivered_and_context_leak_fails(self):
        for mutation in ('failure', 'wrong_text', 'wrong_turn'):
            raw = self.raw(mutation != 'failure')
            if mutation == 'wrong_text':
                raw['events'][0]['response']['content'] = '다른 답'
            if mutation == 'wrong_turn':
                raw['events'][0]['response']['turn'] = 3
            result = analyze_run(historical_run(raw))
            self.assertEqual(result['execution']['ids']['explained'], [])
            self.assertEqual(result['evaluator_separation']['status'], 'FAIL')

    def test_unknown_intent_is_not_inferred_from_sentence(self):
        raw = self.raw()
        del raw['last_reference_context']['current_patient_observations'][1]['intent']
        result = analyze_run(historical_run(raw))
        self.assertEqual(result['execution']['ids']['unclassified_say'], ['E1'])
        self.assertEqual(result['execution']['ids']['explained'], [])

    def test_exam_sdk_result_is_joined_without_importing_unperformed_exam_table(self):
        raw = self.raw()
        raw['events'][0].update(action='EXAM', content='신체 진찰')
        raw['events'][0]['response'] = {'status': 'OK', 'result': '관찰 결과', 'turn': 1}
        raw['last_reference_context']['current_patient_observations'][1].update(
            kind='exam', question='신체 진찰', text='관찰 결과', intent='EXAM')
        run = historical_run(raw)
        self.assertEqual(run['trace'][0]['observation_ids'], ['F2'])
        self.assertEqual(analyze_run(run)['evaluator_separation']['status'], 'PASS')
        raw['last_reference_context']['current_patient_observations'].append(
            {'id': 'F9', 'kind': 'exam', 'question': '다른 진찰', 'text': '미실시 결과', 'consult_action_number': 9})
        self.assertEqual(analyze_run(historical_run(raw))['evaluator_separation']['status'], 'FAIL')

    def test_missing_trace_and_p_only_do_not_pass_delivery(self):
        run = synthetic_run({'final_record': {'P': {'education': '설명 계획'}}})
        result = analyze_run(run)
        self.assertEqual(result['execution']['status'], 'NOT_EVALUATED')
        self.assertFalse(result['execution']['absence_established'])
        self.assertEqual(result['plan_vs_delivery'][0]['status'], 'NOT_EVALUATED')
        self.assertEqual(result['clinical_adequacy'], 'NOT_EVALUATED')

    def test_partial_answer_is_preserved_without_semantic_promotion(self):
        run = synthetic_run({'trace': [{'id': 'T1', 'action': 'SAY', 'intent': 'ASK', 'acknowledged': True,
                                       'content': '복용약과 알레르기가 있나요?', 'response': '약은 먹어요. 이름은 몰라요.'}],
                             'final_record': {'A': '알레르기 없음'}})
        result = analyze_run(run)
        self.assertEqual(result['record_pairs'][0]['status'], 'REVIEW')
        self.assertEqual(result['clinical_adequacy'], 'REVIEW')
        self.assertEqual(run['trace'][0]['response'], '약은 먹어요. 이름은 몰라요.')

    def test_exact_repeat_is_review_even_after_unknown_answer(self):
        run = historical_run(self.raw())
        run['trace'][0].update(intent='ASK', response='잘 모르겠어요.')
        run['trace'].append(dict(run['trace'][0], id='E2'))
        result = analyze_run(run)
        self.assertEqual(result['exact_repeats'][0]['status'], 'REVIEW')

    def test_evaluator_fields_and_forged_observations_cannot_enter_projection(self):
        run = historical_run(self.raw())
        expected = doctor_view(run)
        self.assertEqual(check_doctor_view(expected, run)['status'], 'PASS')
        for kind in ('evaluator', 'forged_id', 'altered_reply'):
            view = copy.deepcopy(expected)
            if kind == 'evaluator':
                view['patient_script'] = 'EVALUATOR_CANARY'
            elif kind == 'forged_id':
                view['observations'][0]['id'] = 'F999'
            else:
                view['observations'][0]['text'] = 'EVALUATOR_CANARY'
            self.assertEqual(check_doctor_view(view, run)['status'], 'FAIL')
        raw = self.raw()
        raw['last_reference_context']['nested'] = {'reference_record': 'EVALUATOR_CANARY'}
        self.assertEqual(analyze_run(historical_run(raw))['evaluator_separation']['status'], 'FAIL')

    def catalog(self, root):
        data = {'trace_complete': True, 'trace': self.raw()['events'], 'final_record': {}}
        data['trace'] = [{'id': 'T1', 'action': 'EXAM', 'content': '진찰', 'response': '관찰', 'acknowledged': True}]
        raw = json.dumps(data).encode()
        (root / 'fixture.json').write_bytes(raw)
        return {'schema_version': 2, 'sources': {'s': {'root': 'repo', 'path': 'fixture.json', 'kind': 'synthetic_example', 'sha256': digest(raw)}},
                'cases': [{'id': 'case', 'domain': 'information', 'provenance': {'kind': 'synthetic'}, 'run_source': 's',
                           'applicability': '조건', 'expected_range': '범위', 'forbidden_errors': '오류', 'human_review': '판단',
                           'evidence': [{'source': 's', 'pointer': '/trace/0', 'id': 'T1'}]}]}

    def test_hash_missing_and_changed_sources_never_pass(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); catalog = self.catalog(root)
            self.assertEqual(load_sources(catalog, root, root)[1]['s']['status'], 'PASS')
            (root / 'fixture.json').write_text('{}', encoding='utf-8')
            self.assertEqual(evaluate(catalog, root, root)['status'], 'FAIL')
            (root / 'fixture.json').unlink()
            result = evaluate(catalog, root, root)
            self.assertEqual(result['sources']['s']['status'], 'NOT_EVALUATED')
            self.assertEqual(result['cases'][0]['status'], 'NOT_EVALUATED')

    def test_bad_pointer_or_wrong_observation_id_fails_integrity(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); catalog = self.catalog(root)
            for ref in ({'source': 's', 'pointer': '/absent'}, {'source': 's', 'pointer': '/trace/0', 'id': 'T2'}):
                catalog['cases'][0]['evidence'] = [ref]
                self.assertEqual(evaluate(catalog, root, root)['status'], 'FAIL')

    def test_human_pass_requires_attribution_and_resolved_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); catalog = self.catalog(root)
            result = evaluate(catalog, root, root)
            self.assertEqual(result['cases'][0]['status'], 'REVIEW')
            self.assertNotIn('original_value', result['cases'][0]['evidence'][0])
            self.assertIn('original_value', evaluate(catalog, root, root, True)['cases'][0]['evidence'][0])
            decision = {'case_id': 'case', 'status': 'PASS', 'reviewer': 'test reviewer', 'reviewed_at': '2026-10-21',
                        'reason': 'synthetic test of attributed decision storage', 'evidence': [{'source': 's', 'pointer': '/trace/0'}]}
            self.assertEqual(evaluate(catalog, root, root, decisions=[decision])['cases'][0]['status'], 'PASS')
            for key in ('reviewer', 'evidence', 'reason'):
                bad = dict(decision); del bad[key]
                with self.assertRaises(ValueError):
                    evaluate(catalog, root, root, decisions=[bad])
            decision['evidence'][0]['pointer'] = '/missing'
            with self.assertRaises(ValueError):
                evaluate(catalog, root, root, decisions=[decision])

    def test_catalog_covers_requested_dimensions_without_clinical_pass(self):
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads((root / 'harness/cases/clinical_review.json').read_text(encoding='utf-8'))
        self.assertEqual(len(catalog['cases']), 10)
        self.assertTrue(all('status' not in c and 'score' not in c for c in catalog['cases']))
        self.assertEqual(len([s for s in catalog['sources'].values() if s['kind'] == 'development_log']), 6)
