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


class WorkflowMockClient(MockClient):
    """Offline transport supporting the medium-only auxiliary calls."""
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
        assert body['reasoning_effort'] == 'medium'
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




def option(action='SAY', content='복용약을 알려주세요', intent='ASK', ids=None, **extra):
    value = {'action': action, 'content': content, 'basis_ids': ids or ['F0'],
             'decision': '현재 관찰에서 처치 판단에 필요한 확인'}
    if action == 'SAY':
        value['intent'] = intent
    value.update(extra)
    return value


def phases(report):
    return Counter(r['phase'] for r in report['budget_ledger']['requests'])


class WorkflowTests(unittest.TestCase):
    def run_case(self, strategy, outputs, *, client=None, replies=(), index=None, **config):
        c = client or WorkflowMockClient(outputs, replies=replies)
        state = loop.State(index or NoResults(), loop.Config(retry_delay=0, **config), strategy=strategy)
        result = loop.consult(c, state)
        self.assertEqual(result, {'accepted': True})
        self.assertEqual(len(c.submissions), 1)
        self.assertFalse(state.report['budget_ledger']['official_or_configured_limit_exceeded'])
        self.assertFalse(state.report['patient_understanding_assessed'])
        self.assertNotIn('TEST', [x['action'] for x in c.calls])
        self.assertTrue(all(b['reasoning_effort'] == 'medium' for b in c.chat_bodies))
        return c, state.report

    def test_h5_auto_plan_without_readiness_and_plan_done_cannot_stop_primary(self):
        outputs = [say('언제 시작됐나요?'), say('복용약을 알려주세요'),
                   {'plan': '미실시 초기 계획', 'next_action': {'action': 'DONE'}},
                   say('약 봉투가 있나요?', plan_update='새 답변에 따른 미실시 수정 계획'),
                   {'action': 'DONE'}, {'plan': '현재 확인으로 충분', 'next_action': {'action': 'DONE'}}, plan()]
        c, r = self.run_case('H5', outputs, replies=['오늘 시작됐어요', '약은 먹지만 이름은 몰라요', '없어요'])
        self.assertEqual(phases(r), Counter(ACTION=4, PLAN=1, REFRESH=1, RECORD=1))
        self.assertEqual(r['actions_succeeded'], 3)
        self.assertEqual(r['auxiliary_events'][0]['status'], 'PLAN_DONE_IGNORED')
        self.assertIn('새 답변에 따른 미실시 수정 계획', c.prompts[4][1]['content'])
        self.assertNotIn('미실시 수정 계획', c.prompts[-1][1]['content'])
        self.assertNotIn('미실시 초기 계획', json.dumps(c.submissions[0], ensure_ascii=False))
        self.assertIn('약은 먹지만 이름은 몰라요', c.submissions[0]['note']['S']['hpi'])

    def test_h5_defers_plan_for_current_urgent_action_and_uses_latest_reply(self):
        def planned(body):
            self.assertEqual(sum(x['action'] == 'SAY' for x in c.calls), 2)
            self.assertIn('지금은 대답할 수 있어요', body['messages'][1]['content'])
            return {'plan': '현재 상태에 맞춘 잠정 계획'}
        outputs = [say('숨쉬기는 어떤가요?', urgent=True), say('바로 도움을 요청하세요', 'EXPLAIN', urgent=True),
                   say('언제부터 시작됐나요?'), planned, {'action': 'DONE'},
                   {'plan': '현재 상태 재검토', 'next_action': {'action': 'DONE'}}, plan()]
        c = WorkflowMockClient(outputs, replies=['어려워요', '지금은 대답할 수 있어요', '조금 전이에요'])
        c, r = self.run_case('H5', [], client=c)
        self.assertEqual(phases(r)['PLAN'], 1)
        self.assertEqual(r['actions_succeeded'], 3)

    def test_h5_first_done_can_be_sufficient_without_forced_actions_or_refresh(self):
        for proposal in ({'plan': '확인 범위와 충분성 검토', 'next_action': {'action': 'DONE'}},
                         {'plan': '확인 범위와 충분성 검토'}):
            c, r = self.run_case('H5', [{'action': 'DONE'}, proposal, plan()])
            self.assertEqual(phases(r), Counter(ACTION=1, PLAN=1, RECORD=1))
            self.assertEqual(r['actions_succeeded'], 0)
            self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')

    def test_h5_refresh_reacts_to_new_observation_once_and_can_deliver_explanation(self):
        def refresh(body):
            self.assertIn('처음과 달라졌어요', body['messages'][1]['content'])
            self.assertIn('clinical_plan_not_patient_facts', body['messages'][1]['content'])
            return {'plan': '새 반응에 따라 계획 변경', 'next_action': say('추가 평가가 필요해요', 'EXPLAIN')}
        c, r = self.run_case('H5', [say('증상은 언제 시작됐나요?'), say('지금 상태는 어떤가요?'),
            {'plan': '초기 잠정 계획'}, {'action': 'DONE'}, refresh, {'action': 'DONE'}, plan()],
            replies=['오늘이요', '처음과 달라졌어요', '무슨 뜻인가요?'])
        self.assertEqual(phases(r)['REFRESH'], 1)
        self.assertEqual(r['acknowledged_explanations'], 1)
        note=c.submissions[0]['note']
        self.assertIn('[실제 SAY 설명]', note['P']['education'])
        self.assertIn('무슨 뜻인가요?', note['S']['hpi'])
        self.assertNotIn('새 반응에 따라 계획 변경', json.dumps(note,ensure_ascii=False))

    def test_h5_bad_plan_does_not_retry_or_block_primary_and_refresh_can_recover(self):
        for bad in ('not-json', {'plan': '가'*1601}, TimeoutError('offline'),
                    {'plan': '미실시', 'next_action': {'action': 'TEST', 'content': 'CT'}}):
            c, r = self.run_case('H5', [say('언제부터인가요?'), say('어디가 아픈가요?'), bad,
                {'action': 'DONE'}, {'plan': '종료 검토', 'next_action': {'action': 'DONE'}}, plan()])
            self.assertEqual(r['actions_succeeded'], 2)
            self.assertEqual(phases(r)['PLAN'], 1)
            self.assertEqual(phases(r)['REFRESH'], 1)
            self.assertEqual(r['model_retries'], 0)
            if isinstance(bad, TimeoutError):
                entry=next(e for e in r['budget_ledger']['requests'] if e['phase']=='PLAN')
                self.assertEqual(entry['state'], 'UNCERTAIN')
                self.assertEqual(entry['reserved'][1], 3072)

    def test_h6_ordered_candidates_select_one_and_discard_stale_remaining(self):
        packet={'next_actions':[option(), option('EXAM','복부 반발통 확인')]}
        c, r = self.run_case('H6', [packet, {'next_actions':[option(content='추가 평가가 필요해요',intent='EXPLAIN',ids=['F2'])]},
                                  {'action':'DONE'}, {'action':'DONE'}, plan()],
                            replies=['약은 먹어요. 이름은 몰라요', '네'])
        self.assertEqual(phases(r), Counter(ACTION=3,AUDIT=1,RECORD=1))
        self.assertEqual(r['action_counts'], {'SAY':2})
        self.assertNotIn('EXAM', [x['action'] for x in c.calls])
        self.assertNotIn('next_actions', c.prompts[1][1]['content'])
        self.assertNotIn('복부 반발통 확인', c.prompts[-1][1]['content'])
        self.assertEqual(r['acknowledged_explanations'],1)

    def test_h6_skips_repeated_or_invalid_candidate_and_executes_real_exam(self):
        invalid=option('TEST','혈액 검사')
        missing=option(ids=['REFERENCE_ONLY'])
        c,r=self.run_case('H6',[{'next_actions':[option()]},
            {'next_actions':[option(), invalid, option('EXAM','복부 반발통 확인',ids=['F2'])]},
            {'next_actions':[missing], **say('추가 평가가 필요해요','EXPLAIN')},
            {'action':'DONE'},{'action':'DONE'},plan()], replies=['약은 먹지만 이름은 몰라요','알겠어요'])
        self.assertEqual(r['action_counts'],{'SAY':2,'EXAM':1})
        self.assertEqual(r['invalid_model_outputs'],0)
        note=c.submissions[0]['note']
        self.assertIn('복부 반발통 확인',note['O']['exam'])
        self.assertIn('복부 압통은 있으나 반발통은 없습니다',note['O']['exam'])
        self.assertEqual(note['O']['tests'],'')
        self.assertNotIn('알레르기 없음',json.dumps(note,ensure_ascii=False))

    def test_h6_single_action_urgent_and_primary_test_contract(self):
        for primary,expected in [(say('바로 도움을 요청하세요','EXPLAIN',urgent=True),'SAY'),
                                 ({'action':'TEST','content':'CT'},None)]:
            packet=dict(primary,next_actions=[option('EXAM','복부 반발통 확인')])
            c,r=self.run_case('H6',[packet,{'action':'DONE'},{'action':'DONE'},plan()])
            self.assertEqual(r['actions_succeeded'],int(expected is not None))
            self.assertNotIn('EXAM',[x['action'] for x in c.calls])
            self.assertEqual(r['invalid_model_outputs'],int(expected is None))

    def test_h6_nfc_and_malformed_optional_packet_preserve_valid_primary(self):
        c,r=self.run_case('H6',[{'next_actions':[option('EXAM','가'*30)]},
            dict(say('어디가 아픈가요?'),next_actions=[option(content='가'*31)]),
            dict(say('언제 시작됐나요?'),next_actions=[option()]*4),{'action':'DONE'},{'action':'DONE'},plan()])
        self.assertEqual(r['action_counts'],{'EXAM':1,'SAY':2})
        self.assertIn('가'*30,c.submissions[0]['note']['O']['exam'])
        self.assertEqual(r['invalid_model_outputs'],0)

    def test_rejected_exam_recovers_without_false_observation(self):
        for strategy in ('H5','H6'):
            for error in ('EXAM_NOT_SPECIFIC','EXAM_NOT_RECOGNIZED'):
                if strategy=='H6':
                    outputs=[{'next_actions':[option('EXAM','복부 반발통 확인')]},
                        {'next_actions':[option('EXAM','복부 반발통 확인'),option()]},
                        {'action':'DONE'},{'action':'DONE'},plan()]
                else:
                    outputs=[{'action':'EXAM','content':'복부 반발통 확인'},say('복용약을 알려주세요'),
                        {'action':'DONE'},{'plan':'미실시 진찰 재검토','next_action':{'action':'DONE'}},plan()]
                c=WorkflowMockClient(outputs,failures={'EXAM':[error]})
                c,r=self.run_case(strategy,[],client=c)
                self.assertEqual(sum(x['action']=='EXAM' for x in c.calls),1)
                self.assertEqual(r['action_counts'],{'SAY':1})
                self.assertIn(error,c.prompts[1][1]['content'])
                self.assertNotIn('복부 반발통 확인',c.submissions[0]['note']['O']['exam'])

    def test_h6_first_done_audit_once_allows_action_or_done(self):
        for suggestion in ({'action':'DONE'},{'action':'ASK','content':'궁금한 점이 있나요?'},
                           {'action':'EXAM','content':'복부 압통 확인'},
                           {'action':'EXPLAIN','content':'더 아프면 응급실로 가세요'}):
            outputs=[{'action':'DONE'},suggestion]
            if suggestion['action']!='DONE':outputs.append({'action':'DONE'})
            outputs.append(plan())
            c,r=self.run_case('H6',outputs)
            self.assertEqual(phases(r)['AUDIT'],1)
            self.assertEqual(r['actions_succeeded'],int(suggestion['action']!='DONE'))
            self.assertEqual(r['termination_reason'],'DOCTOR_DONE')

    def test_auxiliary_invalid_timeout_and_budget_time_limits_preserve_diagnose(self):
        for bad in ('not-json', {'action':'TEST','content':'CT'},TimeoutError('offline')):
            c,r=self.run_case('H6',[{'action':'DONE'},bad,plan()])
            self.assertEqual(r['doctor_http_attempts'],3)
            self.assertEqual(r['actions_succeeded'],0)
            self.assertEqual(r['model_retries'],0)
        for strategy in ('H5','H6'):
            with patch.object(loop.Run,'left',return_value=450):
                c,r=self.run_case(strategy,[{'action':'DONE'},plan()])
            self.assertEqual(r['doctor_http_attempts'],2)
            c,r=self.run_case(strategy,[{'action':'DONE'},plan()],max_doctor_requests=4)
            self.assertEqual(r['doctor_http_attempts'],2)
            self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')

    def test_auxiliary_caps_ledger_and_no_session_state_sharing(self):
        c,r=self.run_case('H5',[say('언제부터인가요?'),say('어디가 아픈가요?'),{'plan':'PRIOR_SESSION_PLAN_MARKER'},
            {'action':'DONE'},{'plan':'수정 계획','next_action':{'action':'DONE'}},plan()])
        entries=r['budget_ledger']['requests']
        for row,body,timeout in zip(entries,c.chat_bodies,c.chat_timeouts):
            expected=3072 if row['phase'] in ('PLAN','REFRESH','AUDIT') else 4096 if row['phase']=='RECORD' else 2048
            self.assertEqual(body['max_tokens'],expected)
            if row['phase'] in ('PLAN','REFRESH','AUDIT'):
                self.assertEqual(row['attempts'],1)
                self.assertLessEqual(timeout,120)
        reserves=[e for e in r['budget_ledger']['events'] if e['event']=='RESERVED' and e['phase'] in ('PLAN','REFRESH')]
        self.assertTrue(all(e['final_headroom_calls']==3 and e['final_headroom_output']==3*4096 for e in reserves))
        c2,r2=self.run_case('H5',[{'action':'DONE'},{'plan':'새 환자 충분성 검토'},plan()])
        self.assertEqual(phases(r2)['PLAN'],1)
        self.assertEqual(phases(r2)['REFRESH'],0)
        self.assertNotIn('PRIOR_SESSION_PLAN_MARKER',json.dumps(c2.prompts,ensure_ascii=False))

    def test_failed_explanation_is_not_recorded_as_delivered(self):
        c=WorkflowMockClient([say('복용약과 알레르기가 있나요?'),{'action':'DONE'},
            {'action':'EXPLAIN','content':'추가 평가가 필요해요'},plan()],
            replies=['약은 먹지만 이름은 몰라요'],failures={'SAY':[None,'API_UNAVAILABLE','API_UNAVAILABLE','API_UNAVAILABLE']})
        c,r=self.run_case('H6',[],client=c)
        self.assertEqual(r['acknowledged_explanations'],0)
        note=c.submissions[0]['note']
        self.assertIn('약은 먹지만 이름은 몰라요',note['S']['hpi'])
        self.assertNotIn('알레르기 없음',json.dumps(note,ensure_ascii=False))
        self.assertNotIn('[실제 SAY 설명]',note['P']['education'])


if __name__ == '__main__':
    unittest.main()
