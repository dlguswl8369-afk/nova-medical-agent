"""Synthetic fixtures only: no public patient script or official answer key."""
import copy
import json
import os
import runpy
import socket
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('NOVA_TEST_APP', str(ROOT / 'app')))
import nova_sdk
from nova_sdk import Client, NovaError, RECORD_FIELDS
from nova_agent import prepare, consult
from nova_agent.loop import Config, State, MODEL
from nova_agent.context import fact, query_from_facts, reference_packet, visible_facts
from nova_agent.record import render_record

REPORTS = {}


def plan():
    return {'diagnosis': '원인 미상 복통', 'diagnosis_basis': ['F0'],
        'source_refs': {s: {f: [] for f in RECORD_FIELDS[s]} for s in ('S', 'O')},
        'assessment': [{'text': '현재 증상으로 원인 확인이 필요함', 'fact_ids': ['F0']}],
        'differential': [], 'plans': {f: '추가 평가 예정' for f in RECORD_FIELDS['P']}}


class MockClient(Client):
    """Override transport only. chat/say/exam/diagnose use unmodified SDK."""
    def __init__(self, outputs=None, failures=None, opening='어제부터 배가 아파요', turns=50):
        super().__init__(api_base='https://nova.snubhai.org', token='SYNTHETIC_NOT_A_KEY')
        self.outputs = list(outputs or [])
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.calls, self.prompts, self.submissions = [], [], []
        self.initial = {'opening': opening, 'vital_signs': {'BP': '120/80', 'temperature': '37.1 C'}}
        self.turns = turns
        self.chat_number = 0

    def _request(self, method, path, body=None):
        action = (body or {}).get('action', 'CHAT' if path.endswith('completions') else 'SESSION')
        self.calls.append({'method': method, 'path': path, 'action': action, 'request_id': (body or {}).get('request_id')})
        queue = self.failures.get(action, [])
        if queue:
            error = queue.pop(0)
            if error:
                raise NovaError(error)
        if action == 'SESSION':
            return {'initial': self.initial, 'turns_remaining': self.turns}
        if action == 'CHAT':
            assert body['model'] == MODEL and body['reasoning_effort'] == 'medium'
            assert body['max_tokens'] <= 8000
            self.prompts.append(copy.deepcopy(body['messages']))
            self.chat_number += 1
            output = self.outputs.pop(0) if self.outputs else plan()
            if callable(output):
                output = output(body)
            return {'choices': [{'message': {'content': output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)}}], 'usage': {'prompt_tokens': 300, 'completion_tokens': 100}}
        if action == 'SAY':
            self.turns -= 1
            return {'content': '어제 저녁부터 시작했어요', 'turns_remaining': self.turns}
        if action == 'EXAM':
            self.turns -= 1
            return {'result': '복부 압통은 있으나 반발통은 없습니다', 'turns_remaining': self.turns}
        if action == 'DIAGNOSE':
            self.submissions.append(copy.deepcopy(body))
            return {'accepted': True}
        raise AssertionError('Forbidden or undocumented endpoint/action: ' + action)


class NoResults:
    def search(self, *args, **kwargs):
        return []


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = prepare().index

    def run_case(self, client, config=None, index=None):
        state = State(index or self.index, config or Config(retry_delay=0))
        try:
            with patch.object(socket, 'create_connection', side_effect=AssertionError('NETWORK_FORBIDDEN')), patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NETWORK_FORBIDDEN')):
                result = consult(client, state)
            self.assertEqual(result, {'accepted': True})
            self.assertEqual(len(client.submissions), 1)
            self.assertFalse(any(c['action'] == 'TEST' for c in client.calls))
            return state.report
        finally:
            REPORTS[self.id().split('.')[-1]] = state.report
            if self.id().endswith('test_full_flow_observations_and_sdk') and client.submissions:
                output = Path(os.environ.get('NOVA_TEST_OUTPUT_DIR', str(ROOT/'reports/test_runs'/('direct_'+uuid.uuid4().hex))))
                output.mkdir(parents=True, exist_ok=True)
                (output / 'synthetic_flow_example.json').write_text(json.dumps({
                    'synthetic_only': True, 'diagnosis_not_scored': True, 'sdk_calls': client.calls,
                    'submitted_note': client.submissions[-1]['note'], 'diagnosis': client.submissions[-1]['diagnosis']}, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_full_flow_observations_and_sdk(self):
        p = plan()
        p['source_refs']['S']['hpi'] = ['F2']
        p['source_refs']['O']['exam'] = ['F3']
        client = MockClient([{'action': 'SAY', 'content': '언제부터 아팠나요?'}, {'action': 'EXAM', 'content': '복부 반발통을 확인하겠습니다'}, {'action': 'SAY', 'content': '추가 평가가 필요합니다', 'intent': 'EXPLAIN'}, {'action': 'DONE'}, p])
        r = self.run_case(client)
        self.assertTrue(r['successful_execution'])
        self.assertEqual(r['actions_succeeded'], 3)
        self.assertEqual(r['doctor_http_attempts'], 5)
        note = client.submissions[0]['note']
        self.assertIn('어제 저녁', note['S']['hpi'])
        self.assertIn('시행한 진찰', note['O']['exam'])
        self.assertEqual(note['O']['tests'], '')
        self.assertIn('[실제 SAY 설명]', note['P']['education'])
        contexts = [json.loads(p[1]['content']) for p in client.prompts]
        self.assertTrue(contexts[0]['reference_evidence'])
        self.assertEqual(contexts[0]['current_patient_observations'][0]['id'], 'F0')
        self.assertTrue(all(r['not_current_patient_facts'] for r in contexts[0]['reference_evidence']))

    def test_no_retrieval_results(self):
        r = self.run_case(MockClient([{'action': 'DONE'}, plan()]), index=NoResults())
        self.assertEqual(r['empty_retrievals'], 1)
        self.assertEqual(r['retrieval_cache_hits'], 1)
        self.assertTrue(r['successful_execution'])

    def test_invalid_test_long_action_and_json_recovered(self):
        client = MockClient([{'action': 'TEST', 'content': 'CT 검사'}, {'action': 'SAY', 'content': '가' * 31}, {'action': 'DONE'}, 'not json', plan()])
        r = self.run_case(client)
        self.assertEqual(r['invalid_model_outputs'], 3)
        self.assertFalse(any(c['action'] in ('SAY', 'EXAM') for c in client.calls))

    def test_malformed_exhaustion_degrades(self):
        r = self.run_case(MockClient(['[]', 'oops', {'action': 'TEST'}, plan()]))
        self.assertTrue(r['submitted'])
        self.assertFalse(r['successful_execution'])

    def test_reference_id_cannot_be_patient_fact(self):
        bad = plan()
        bad['source_refs']['S']['hpi'] = ['page:fake-reference']
        c = MockClient([{'action': 'DONE'}, bad, bad, bad])
        r = self.run_case(c)
        self.assertTrue(r['degraded'])
        self.assertTrue(r['diagnosis_unresolved'])
        self.assertNotIn('page:fake', json.dumps(c.submissions))

    def test_exam_cannot_be_subjective_or_test(self):
        facts = [fact('F0', 'opening', '통증'), fact('F1', 'vitals', '정상'), fact('F2', 'exam', '압통')]
        p = plan()
        p['source_refs']['S']['pmh'] = ['F2']
        with self.assertRaises(ValueError):
            render_record(p, facts, [])
        p = plan()
        p['source_refs']['O']['tests'] = ['F2']
        with self.assertRaises(ValueError):
            render_record(p, facts, [])

    def test_transient_model_retry_same_request_id(self):
        c = MockClient([{'action': 'DONE'}, plan()], {'CHAT': ['PROVIDER_UNAVAILABLE', None]})
        r = self.run_case(c)
        chats = [x for x in c.calls if x['action'] == 'CHAT']
        self.assertEqual(chats[0]['request_id'], chats[1]['request_id'])
        self.assertEqual(r['doctor_http_attempts'], 3)
        self.assertEqual(r['doctor_unique_requests'], 2)

    def test_model_outage_fallback(self):
        c = MockClient(failures={'CHAT': ['PROVIDER_UNAVAILABLE'] * 6})
        r = self.run_case(c)
        self.assertTrue(r['degraded'])
        self.assertEqual(r['doctor_http_attempts'], 6)
        self.assertEqual(c.submissions[0]['diagnosis'], '진단 미정')

    def test_action_and_submission_retry_idempotent(self):
        c = MockClient([{'action': 'SAY', 'content': '언제 시작했나요?'}, {'action': 'DONE'}, plan()], {'SAY': ['API_UNAVAILABLE', None], 'DIAGNOSE': ['REQUEST_PENDING', None]})
        self.run_case(c)
        for action in ('SAY', 'DIAGNOSE'):
            calls = [x for x in c.calls if x['action'] == action]
            self.assertEqual(calls[0]['request_id'], calls[1]['request_id'])

    def test_turn_limit_and_repeat(self):
        c = MockClient([{'action': 'SAY', 'content': '언제 시작했나요?'}, plan()], turns=1)
        self.run_case(c)
        self.assertEqual(sum(x['action'] == 'SAY' for x in c.calls), 1)
        c = MockClient([{'action': 'SAY', 'content': '언제 시작했나요?'}, {'action': 'SAY', 'content': '언제 시작했나요?'}, {'action': 'DONE'}, plan()])
        r = self.run_case(c)
        self.assertEqual(r['invalid_model_outputs'], 1)
        self.assertEqual(r['actions_succeeded'], 1)

    def test_model_call_budget_reserved_for_record(self):
        r = self.run_case(MockClient(), Config(max_doctor_requests=1, retry_delay=0))
        self.assertEqual(r['doctor_http_attempts'], 1)
        self.assertTrue(r['submitted'])
        self.assertTrue(r['degraded'])

    def test_token_budget_no_overshoot(self):
        c = MockClient()
        r = self.run_case(c, Config(max_input_budget=100, max_output_budget=100, retry_delay=0))
        self.assertEqual(r['doctor_http_attempts'], 0)
        self.assertTrue(r['diagnosis_unresolved'])

    def test_deadline_stops_without_action(self):
        class Expired(MockClient):
            def session(self):
                return {**super().session(), 'deadline': '2020-01-01T00:00:00+00:00'}
        state = State(self.index, Config(retry_delay=0))
        with self.assertRaises(NovaError) as caught:
            consult(Expired(), state)
        self.assertEqual(caught.exception.code, 'LOCAL_DEADLINE')
        self.assertFalse(state.report['submitted'])

    def test_closed_session_fails_without_false_success(self):
        c = MockClient(failures={'CHAT': ['SESSION_CLOSED']})
        state = State(self.index, Config(retry_delay=0))
        with self.assertRaises(NovaError):
            consult(c, state)
        self.assertFalse(state.report['submitted'])
        self.assertFalse(c.submissions)

    def test_long_context_whole_observations_only(self):
        facts = [fact('F0', 'opening', '통증'), fact('F1', 'vitals', '37도')]
        facts += [fact('F' + str(i), 'patient_reply', '가' * 9000) for i in range(2, 52)]
        visible = visible_facts(facts)
        self.assertLessEqual(len(json.dumps(visible, ensure_ascii=False)), 22000)
        self.assertLess(len(visible), len(facts))
        self.assertTrue(all(f['text'] == '가' * 9000 for f in visible[2:]))
        self.assertLessEqual(len(query_from_facts(facts)), 1800)
        c = MockClient([{'action': 'DONE'}, plan()], opening='복통 ' * 3000)
        r = self.run_case(c)
        self.assertTrue(r['submitted'])
        self.assertLess(r['max_prompt_chars'], 40000)

    def test_duplicate_and_oversize_evidence(self):
        from nova_agent import context
        hit = copy.deepcopy(self.index.records[0])
        class DuplicateIndex:
            records = [hit, hit, hit]
            def search(self, *args, **kwargs):
                return self.records
            def get_parent(inner, key):
                return self.index.get_parent(key)
        rows = reference_packet(DuplicateIndex(), '복통', max_chars=12000)
        self.assertEqual(len(rows), 1)
        audit = {}
        rows = reference_packet(DuplicateIndex(), '복통', max_chars=128, audit=audit)
        self.assertEqual(rows, [])
        self.assertTrue(all(e['reason'] == 'COMPLETE_UNIT_OVER_BUDGET' for e in audit['excluded']))

    def test_explicit_source_llm_restriction(self):
        from nova_agent.policy import research_decision
        hit = copy.deepcopy(self.index.records[0])
        self.assertIs(hit['source_metadata']['llm_processing_allowed'], False)
        self.assertTrue(research_decision(hit)[0])
        hit['source_metadata']['explicit_publisher_llm_prohibition'] = True
        self.assertEqual(research_decision(hit), (False, 'PUBLISHER_RESTRICTION'))

    def test_doctor_receives_usable_reference_and_uses_it_for_step(self):
        def choose_using_evidence(body):
            context = json.loads(body['messages'][1]['content'])
            references = [r for r in context['reference_evidence'] if r['text']]
            self.assertTrue(references)
            self.assertTrue(all(r['evidence_ids'] and r['document_type'] for r in references))
            return {'action': 'SAY', 'content': '최근 해외여행을 다녀오셨나요?'}
        c = MockClient([choose_using_evidence, {'action': 'DONE'}, plan()], opening='malaria fever chills mosquito')
        self.run_case(c)
        self.assertEqual(sum(x['action'] == 'SAY' for x in c.calls), 1)

    def test_rejected_exam_is_not_an_observation(self):
        c = MockClient([{'action': 'EXAM', 'content': '복부 확인'}, {'action': 'DONE'}, plan()], {'EXAM': ['EXAM_NOT_SPECIFIC']})
        r = self.run_case(c)
        self.assertEqual(r['observed_fact_count'], 2)
        self.assertNotIn('복부 확인', c.submissions[0]['note']['O']['exam'])
        second = json.loads(c.prompts[1][1]['content'])
        self.assertIn('EXAM_NOT_SPECIFIC', second['recent_action_error_codes_not_patient_facts'])

    def test_malformed_sdk_completion_is_recovered(self):
        class BadCompletion(MockClient):
            bad = True
            def chat(self, *args, **kwargs):
                if self.bad:
                    self.bad = False
                    return []
                return super().chat(*args, **kwargs)
        r = self.run_case(BadCompletion([{'action': 'DONE'}, plan()]))
        self.assertEqual(r['invalid_model_outputs'], 1)

    def test_wrong_observation_shape_does_not_enter_note(self):
        class BadReply(MockClient):
            def say(self, *args, **kwargs):
                return {'content': '알 수 없음', 'turns_remaining': 'invalid'}
        c = BadReply([{'action': 'SAY', 'content': '언제 시작했나요?'}, plan()])
        r = self.run_case(c)
        self.assertTrue(r['degraded'])
        self.assertEqual(r['observed_fact_count'], 2)
        self.assertNotIn('알 수 없음', json.dumps(c.submissions, ensure_ascii=False))

    def test_prepare_and_search_without_network(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('NETWORK_FORBIDDEN')), patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NETWORK_FORBIDDEN')):
            state = prepare()
            self.assertTrue(state.index.search('복통 설사 항생제'))

    def test_official_prepare_ready_consult_order(self):
        events = []
        class Stub:
            def ready(self):
                events.append('ready')
        def prep():
            events.append('prepare')
            return 'loaded_index'
        def con(client, state):
            self.assertEqual(state, 'loaded_index')
            events.append('consult')
        with patch.object(nova_sdk, 'Client', Stub):
            nova_sdk.run_agent(prep, con)
        self.assertEqual(events, ['prepare', 'ready', 'consult'])

    def test_actual_run_entrypoint_with_official_sdk(self):
        c = MockClient([{'action': 'DONE'}, plan()])
        with patch.object(nova_sdk, 'Client', return_value=c), patch.object(socket, 'socket', side_effect=AssertionError('NETWORK_FORBIDDEN')):
            runpy.run_path(str(Path(os.environ.get('NOVA_TEST_APP', str(ROOT / 'app'))) / 'run.py'), run_name='__main__')
        self.assertEqual(c.calls[0]['path'], '/_nova/ready')
        self.assertEqual(c.calls[1]['path'], '/v1/session')
        self.assertEqual(c.calls[-1]['action'], 'DIAGNOSE')

    def test_config_rejects_over_official_limits(self):
        for args in ({'max_turns': 51}, {'max_doctor_requests': 201}, {'max_input_budget': 500001}, {'max_output_budget': 100001}):
            with self.assertRaises(ValueError):
                Config(**args)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AgentTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    output = Path(os.environ.get('NOVA_TEST_REPORT', str(ROOT / 'reports/loop_tests.json')))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'synthetic_only': True, 'real_server_calls': 0, 'test_count': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors), 'success': result.wasSuccessful(),
        'scope': 'SDK transport mocked; tests verify execution and invariants, not diagnostic correctness or scored clinical quality.',
        'scenario_reports': REPORTS}, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.exit(not result.wasSuccessful())
