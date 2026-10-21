"""Synthetic execution regressions, not clinical judgment or score evidence.

Only the transport is replaced. The real SDK, action parser, observations,
record renderer and request ledger remain on the exercised execution path.
"""
import copy
import json
import socket
import unittest
from collections import Counter
from unittest.mock import patch

from test_agent import MockClient, NoResults, plan
from test_simple_v35 import say
from nova_agent import loop
from nova_sdk import NovaError


class HighMockClient(MockClient):
    """Offline transport supporting the narrowly permitted high audit call."""
    def __init__(self, outputs=None, replies=(), **kwargs):
        super().__init__(outputs=outputs, **kwargs)
        self.replies = iter(replies)
        self.chat_bodies, self.chat_timeouts = [], []

    def _request(self, method, path, body=None):
        if not path.endswith('completions'):
            return super()._request(method, path, body)
        self.calls.append({'method': method, 'path': path, 'action': 'CHAT',
                           'request_id': (body or {}).get('request_id')})
        self.chat_bodies.append(copy.deepcopy(body))
        self.chat_timeouts.append(self.timeout)
        assert body['model'] == loop.MODEL
        assert body['reasoning_effort'] in ('medium', 'high')
        assert body['max_tokens'] <= 4096
        queue = self.failures.get('CHAT', [])
        if queue:
            error = queue.pop(0)
            if error:
                raise NovaError(error)
        self.prompts.append(copy.deepcopy(body['messages']))
        self.chat_number += 1
        output = self.outputs.pop(0) if self.outputs else plan()
        if callable(output):
            output = output(body)
        if isinstance(output, BaseException):
            raise output
        return {'choices': [{'message': {'content': output if isinstance(output, str)
                 else json.dumps(output, ensure_ascii=False)}}],
                'usage': {'prompt_tokens': 300, 'completion_tokens': 100}}

    def say(self, **kwargs):
        response = super().say(**kwargs)
        response['content'] = next(self.replies, response['content'])
        return response


def exam_choice(**extra):
    option = {'content': '복부 반발통 확인', 'basis_ids': ['F0'],
              'decision': '복막 자극 여부에 따라 의뢰 판단'}
    option.update(extra)
    return say('통증은 어디인가요?', prefer_exam=True, exam_option=option)


def phases(report):
    return Counter(r['phase'] for r in report['budget_ledger']['requests'])


def contexts(client):
    return [json.loads(p[1]['content']) for p in client.prompts]


class HighIntensityTests(unittest.TestCase):
    def run_case(self, strategy, outputs, *, client=None, replies=(), index=None, **config):
        c = client or HighMockClient(outputs, replies=replies)
        state = loop.State(index or NoResults(), loop.Config(retry_delay=0, **config),
                           strategy=strategy)
        with patch.object(socket, 'create_connection', side_effect=AssertionError('NETWORK_FORBIDDEN')), \
                patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NETWORK_FORBIDDEN')):
            result = loop.consult(c, state)
        self.assertEqual(result, {'accepted': True})
        self.assertEqual(len(c.submissions), 1)
        self.assertTrue(state.report['submitted'])
        self.assertFalse(state.report['budget_ledger']['official_or_configured_limit_exceeded'])
        self.assertNotIn('TEST', [x['action'] for x in c.calls])
        self.assertFalse(state.report['patient_understanding_assessed'])
        return c, state.report

    def test_four_variants_have_distinct_auxiliary_paths_and_done_allowed(self):
        for strategy in ('H1', 'H2', 'H3', 'H4'):
            with self.subTest(strategy=strategy):
                outputs = [{'action': 'DONE'}]
                if strategy in ('H3', 'H4'):
                    outputs.append({'action': 'DONE'})
                outputs.append(plan())
                c, r = self.run_case(strategy, outputs)
                self.assertEqual(phases(r)['PLAN'], 0)
                self.assertEqual(phases(r)['AUDIT'], int(strategy in ('H3', 'H4')))
                self.assertEqual(r['actions_succeeded'], 0)
                self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')
                self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
                self.assertEqual(c.submissions[0]['note']['O']['tests'], '')

    def test_plan_is_after_real_response_and_never_a_fact_or_record_input(self):
        marker = '未実施_SYNTHETIC_PLAN_MARKER'
        replacement = '更新_SYNTHETIC_PLAN_MARKER'
        partial = '약은 먹어요. 이름은 몰라요.'
        captured = []
        class SearchSpy(NoResults):
            def __init__(self):
                self.queries = []
            def search(self, query, *args, **kwargs):
                self.queries.append(query)
                return []
        index = SearchSpy()
        def planner(body):
            captured.append(json.loads(body['messages'][1]['content']))
            self.assertIn(partial, body['messages'][1]['content'])
            return {'plan': marker, 'next_action': {'action': 'EXAM', 'content': '복부 반발통 확인'}}
        outputs = [say('복용약을 알려주세요'), say('어디가 아픈가요?', planning_ready=True, urgent=False),
                   planner, say('약 봉투가 있나요?', plan_update=replacement),
                   {'action': 'DONE'}, plan()]
        c, r = self.run_case('H1', outputs, replies=[partial, '지금은 없어요'], index=index)
        self.assertEqual(phases(r)['PLAN'], 1)
        self.assertEqual(r['action_counts'], {'SAY': 2, 'EXAM': 1})
        self.assertTrue(captured)
        all_contexts = contexts(c)
        self.assertTrue(any(marker in json.dumps(v, ensure_ascii=False) for v in all_contexts[3:-1]))
        self.assertTrue(any(replacement in json.dumps(v, ensure_ascii=False) for v in all_contexts[4:-1]))
        self.assertNotIn(marker, json.dumps(all_contexts[-1], ensure_ascii=False))
        self.assertNotIn(replacement, json.dumps(all_contexts[-1], ensure_ascii=False))
        for ctx in all_contexts:
            self.assertNotIn(marker, json.dumps(ctx['current_patient_observations'], ensure_ascii=False))
        note = json.dumps(c.submissions[0]['note'], ensure_ascii=False)
        self.assertIn(partial, note)
        self.assertNotIn(marker, note)
        self.assertNotIn(replacement, note)
        self.assertNotIn(marker, json.dumps(index.queries, ensure_ascii=False))
        self.assertNotIn(replacement, json.dumps(index.queries, ensure_ascii=False))

    def test_readiness_is_not_inherited_and_initial_action_is_never_delayed(self):
        c, r = self.run_case('H1', [say('숨쉬기 어렵나요?', planning_ready=True, urgent=False),
                                  say('언제부터 시작됐나요?'), {'action': 'DONE'}, plan()],
                            replies=['네, 갑자기 힘들어요', '방금 시작됐어요'])
        self.assertEqual(phases(r)['PLAN'], 0)
        self.assertEqual(r['actions_succeeded'], 2)
        self.assertIn('네, 갑자기 힘들어요', c.prompts[1][1]['content'])

    def test_urgent_current_action_skips_plan_and_exam_override(self):
        current = exam_choice()
        current.update(planning_ready=True, urgent=True)
        c, r = self.run_case('H4', [say('숨쉬기는 어떤가요?'), current,
                                  {'action': 'DONE'}, {'action': 'DONE'}, plan()],
                            replies=['지금 숨쉬기 어려워요', '가슴이 아파요'])
        self.assertEqual(phases(r)['PLAN'], 0)
        self.assertEqual(r['action_counts'], {'SAY': 2})
        self.assertIn('지금 숨쉬기 어려워요', c.prompts[1][1]['content'])

    def test_h2_selects_grounded_exam_in_same_call_and_routes_original_to_o(self):
        choice = exam_choice(basis_ids=['F2'])
        c, r = self.run_case('H2', [say('약을 복용하나요?'), choice, {'action': 'DONE'}, plan()],
                            replies=['약은 먹지만 이름은 몰라요'])
        self.assertEqual(phases(r), Counter(ACTION=3, RECORD=1))
        self.assertEqual(r['action_counts'], {'SAY': 1, 'EXAM': 1})
        note = c.submissions[0]['note']
        self.assertIn('약은 먹지만 이름은 몰라요', note['S']['hpi'])
        self.assertIn('복부 반발통 확인', note['O']['exam'])
        self.assertIn('복부 압통은 있으나 반발통은 없습니다', note['O']['exam'])
        self.assertEqual(note['O']['tests'], '')
        self.assertNotIn('약 없음', json.dumps(note, ensure_ascii=False))

    def test_invalid_exam_options_fall_back_to_primary_without_autoconversion(self):
        invalid = [dict(basis_ids=['REFERENCE_NOT_OBSERVED']), dict(basis_ids='F0'),
                   dict(decision=''), dict(content='가' * 31),
                   dict(action='TEST', content='혈액 검사')]
        for extra in invalid:
            with self.subTest(extra=extra):
                c, r = self.run_case('H2', [exam_choice(**extra), {'action': 'DONE'}, plan()])
                self.assertEqual(r['action_counts'], {'SAY': 1})
                self.assertEqual(r['invalid_model_outputs'], 0)
                self.assertNotIn('EXAM', [x['action'] for x in c.calls])

    def test_nfc_limit_and_forbidden_primary_remain_enforced_before_exam_choice(self):
        c, r = self.run_case('H2', [exam_choice(content='가' * 30), {'action': 'DONE'}, plan()])
        self.assertEqual(r['action_counts'], {'EXAM': 1})
        self.assertIn('가' * 30, c.submissions[0]['note']['O']['exam'])
        prohibited = exam_choice()
        prohibited.update(action='TEST', content='CT 촬영')
        c, r = self.run_case('H2', [prohibited, {'action': 'DONE'}, plan()])
        self.assertEqual(r['actions_succeeded'], 0)
        self.assertEqual(r['invalid_model_outputs'], 1)

    def test_rejected_exam_preserves_reason_and_recovers_without_creating_facts(self):
        for reason in ('EXAM_NOT_SPECIFIC', 'EXAM_NOT_RECOGNIZED'):
            with self.subTest(reason=reason):
                c = HighMockClient([exam_choice(), exam_choice(), {'action': 'DONE'}, plan()],
                                   failures={'EXAM': [reason]})
                c, r = self.run_case('H2', [], client=c)
                self.assertEqual(r['action_counts'], {'SAY': 1})
                self.assertEqual(sum(x['action'] == 'EXAM' for x in c.calls), 1)
                self.assertEqual(r['observed_fact_count'], 3)
                second = contexts(c)[1]
                self.assertIn(reason, json.dumps(second, ensure_ascii=False))
                self.assertIn('복부 반발통 확인', json.dumps(second, ensure_ascii=False))
                self.assertNotIn('복부 반발통 확인', json.dumps(second['current_patient_observations'], ensure_ascii=False))
                self.assertNotIn('복부 반발통 확인', c.submissions[0]['note']['O']['exam'])
                self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
                self.assertLessEqual(r['doctor_http_attempts'], 4)

    def test_first_done_audit_can_propose_action_once_then_allow_done(self):
        for action, intent in (('ASK', 'ASK'), ('EXPLAIN', 'EXPLAIN'), ('EXAM', None)):
            with self.subTest(action=action):
                suggestion = {'action': action, 'content': '복부 압통 확인' if action == 'EXAM' else
                              '지금 궁금한 점이 있나요?' if action == 'ASK' else '더 아프면 응급실로 가세요'}
                c, r = self.run_case('H3', [{'action': 'DONE'}, suggestion, {'action': 'DONE'}, plan()])
                self.assertEqual(phases(r)['AUDIT'], 1)
                self.assertEqual(r['actions_succeeded'], 1)
                self.assertEqual(r['acknowledged_explanations'], int(intent == 'EXPLAIN'))
                self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')

    def test_malformed_or_failed_audit_falls_back_to_original_done_without_retry(self):
        invalid = ['not-json', {'action': 'TEST', 'content': '혈액 검사'},
                   {'action': 'SAY', 'content': '가' * 31}, {'action': 'ASK'},
                   TimeoutError('synthetic timeout')]
        for suggestion in invalid:
            with self.subTest(suggestion=type(suggestion).__name__):
                c, r = self.run_case('H3', [{'action': 'DONE'}, suggestion, plan()])
                self.assertEqual(phases(r)['AUDIT'], 1)
                self.assertEqual(r['doctor_http_attempts'], 3)
                self.assertEqual(r['actions_succeeded'], 0)
                self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')
                self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
                self.assertEqual(r['model_retries'], 0)
                if isinstance(suggestion, TimeoutError):
                    audit = next(row for row in r['budget_ledger']['requests'] if row['phase'] == 'AUDIT')
                    self.assertEqual(audit['state'], 'UNCERTAIN')
                    self.assertEqual(audit['reserved'][1], 3072)

    def test_failed_plan_is_not_retried_and_primary_action_still_executes(self):
        for output in ('not-json', {'plan': '가' * 1601}, TimeoutError('synthetic timeout'),
                       {'plan': '미실시 계획', 'next_action': {'action': 'TEST', 'content': '혈액 검사'}}):
            with self.subTest(output=type(output).__name__):
                c, r = self.run_case('H1', [say('언제 시작됐나요?'),
                    say('어디가 아픈가요?', planning_ready=True, urgent=False), output,
                    say('움직이면 더 아픈가요?', planning_ready=True, urgent=False),
                    {'action': 'DONE'}, plan()])
                self.assertEqual(phases(r)['PLAN'], 1)
                self.assertEqual(r['action_counts'], {'SAY': 3})
                self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')

    def test_auxiliary_time_and_call_gates_preserve_final_record_submission(self):
        with patch.object(loop.Run, 'left', return_value=450):
            c, r = self.run_case('H4', [say('언제 시작됐나요?'),
                say('어디가 아픈가요?', planning_ready=True, urgent=False), {'action': 'DONE'}, plan()])
        self.assertEqual(phases(r)['PLAN'] + phases(r)['AUDIT'], 0)
        self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
        c, r = self.run_case('H3', [{'action': 'DONE'}, plan()], max_doctor_requests=4)
        self.assertEqual(phases(r)['AUDIT'], 0)
        self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
        self.assertLessEqual(r['doctor_http_attempts'], 4)
        c, r = self.run_case('H1', [say('언제 시작됐나요?'),
            say('어디가 아픈가요?', planning_ready=True, urgent=False), plan()], max_doctor_requests=5)
        self.assertEqual(phases(r)['PLAN'], 0)
        self.assertTrue(r['submitted'])
        self.assertLessEqual(r['doctor_http_attempts'], 5)

    def test_h4_two_auxiliary_calls_are_accounted_and_high_is_audit_only(self):
        outputs = [say('언제 시작됐나요?'), say('어디가 아픈가요?', planning_ready=True, urgent=False),
                   {'plan': '관찰에 따라 필요한 확인을 선택'}, {'action': 'DONE'},
                   {'action': 'EXPLAIN', 'content': '더 아프면 응급실로 가세요'},
                   {'action': 'DONE'}, plan()]
        c, r = self.run_case('H4', outputs)
        self.assertEqual(phases(r), Counter(ACTION=4, PLAN=1, AUDIT=1, RECORD=1))
        requests = r['budget_ledger']['requests']
        self.assertEqual(len(requests), len(c.chat_bodies))
        for row, body, timeout in zip(requests, c.chat_bodies, c.chat_timeouts):
            expected = 4096 if row['phase'] in ('AUDIT', 'RECORD') else 3072 if row['phase'] == 'PLAN' else 2048
            self.assertEqual(body['max_tokens'], expected)
            self.assertEqual(body['reasoning_effort'], 'high' if row['phase'] == 'AUDIT' else 'medium')
            self.assertEqual(row['attempts'], 1)
            self.assertEqual(row['state'], 'SETTLED')
            if row['phase'] in ('PLAN', 'AUDIT'):
                self.assertLessEqual(timeout, 180 if row['phase'] == 'AUDIT' else 120)
            if row['phase'] == 'AUDIT':
                self.assertNotIn('clinical_plan_not_patient_facts', body['messages'][1]['content'])
                self.assertNotIn('관찰에 따라 필요한 확인을 선택', body['messages'][1]['content'])
        reservations = [e for e in r['budget_ledger']['events'] if e['event'] == 'RESERVED' and e['phase'] in ('PLAN', 'AUDIT')]
        self.assertTrue(all(e['final_headroom_calls'] == 3 for e in reservations))
        self.assertTrue(all(e['final_headroom_output'] == 3 * 4096 for e in reservations))
        # A fresh consultation must not inherit the earlier planner or audit state.
        c2, r2 = self.run_case('H4', [{'action': 'DONE'}, {'action': 'DONE'}, plan()])
        self.assertEqual(phases(r2)['PLAN'], 0)
        self.assertEqual(phases(r2)['AUDIT'], 1)
        self.assertNotIn('관찰에 따라 필요한 확인을 선택', json.dumps(contexts(c2), ensure_ascii=False))

    def test_high_audit_falls_back_to_medium_when_time_is_tighter(self):
        with patch.object(loop.Run, 'left', return_value=550):
            c, r = self.run_case('H4', [{'action': 'DONE'}, {'action': 'DONE'}, plan()])
        self.assertEqual(phases(r)['AUDIT'], 1)
        self.assertTrue(all(b['reasoning_effort'] == 'medium' for b in c.chat_bodies))
        self.assertEqual(c.chat_bodies[1]['max_tokens'], 3072)
        self.assertLessEqual(c.chat_timeouts[1], 120)

    def test_partial_reply_actual_delivery_and_record_education_are_separate(self):
        partial = '약은 먹어요. 이름은 몰라요.'
        explanation = '더 아프면 응급실로 가세요'
        for success in (True, False):
            with self.subTest(delivery_success=success):
                outputs = [say('복용약과 알레르기가 있나요?'), {'action': 'DONE'},
                           {'action': 'EXPLAIN', 'content': explanation}]
                outputs += ([{'action': 'DONE'}] if success else []) + [plan()]
                c = HighMockClient(outputs, replies=[partial, '무슨 뜻인가요?'])
                if not success:
                    c.failures['SAY'] = [None, 'API_UNAVAILABLE', 'API_UNAVAILABLE', 'API_UNAVAILABLE']
                c, r = self.run_case('H3', [], client=c)
                note = c.submissions[0]['note']
                self.assertIn(partial, note['S']['hpi'])
                self.assertNotIn('알레르기 없음', json.dumps(note, ensure_ascii=False))
                self.assertEqual(r['acknowledged_explanations'], int(success))
                self.assertEqual('[실제 SAY 설명]' in note['P']['education'], success)
                self.assertNotIn('환자 이해 완료', json.dumps(note, ensure_ascii=False))
                if success:
                    self.assertIn('이해 여부는 미확인', note['P']['education'])
                    self.assertIn('무슨 뜻인가요?', note['S']['hpi'])


if __name__ == '__main__':
    unittest.main()
