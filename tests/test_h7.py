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


class H7MockClient(MockClient):
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


from nova_agent.closed_loop import GoalExecutor, GOALS
from nova_agent.prompts import RECORD


def goal(gid='G1', kind='ASK', content='복용약을 알려주세요', **changes):
    value = dict(id=gid, kind=kind, content=content, importance='important',
                 reason='현재 판단에 필요한 확인', condition='현재 증상이 지속되는 상황',
                 basis_ids=['F0'], currently_needed=True)
    value.update(changes)
    return value


def reviewed_done(body, needed=None, **updates):
    ctx = json.loads(body['messages'][1]['content']).get('closed_loop_not_patient_facts', {})
    ids = needed if needed is not None else [g['id'] for g in ctx.get('goals', [])]
    return {'action': 'DONE', 'goal_review': dict(revision=ctx.get('revision', 0), needed=ids, **updates)}


def counterfactual_scenario():
    """After the opening question the Doctor selects DONE every time.

    Follow-up action JSON exists only in the goals. Thus removing choose()
    eliminates all three subsequent SDK actions without changing the Doctor.
    Goals/need judgments are synthetic; this does not test medical reasoning.
    """
    primary = []
    def respond(body):
        system, user = [m['content'] for m in body['messages']]
        if system == RECORD:
            assert 'closed_loop_not_patient_facts' not in user
            return plan()
        if system == GOALS:
            assert '오늘 시작됐어요' in user
            return {'goals': [goal(), goal('G2', 'EXAM', '복부 반발통 확인'),
                              goal('G3', 'EXPLAIN', '추가 평가가 필요해요')]}
        primary.append('ASK' if not primary else 'DONE')
        return say('언제 시작됐나요?') if len(primary) == 1 else reviewed_done(body)
    client = H7MockClient([respond] * 20, replies=['오늘 시작됐어요', '약은 먹지만 이름은 몰라요', '무슨 뜻인가요?'])
    return client, primary


class H7Tests(unittest.TestCase):
    def run_case(self, outputs=None, *, client=None, strategy='H7', **config):
        c = client or H7MockClient(outputs)
        cfg = dict(max_turns=40 if strategy == 'H7' else 30, retry_delay=0)
        cfg.update(config)
        state = loop.State(NoResults(), loop.Config(**cfg), strategy=strategy)
        result = loop.consult(c, state)
        self.assertEqual(result, {'accepted': True})
        self.assertEqual(len(c.submissions), 1)
        self.assertFalse(state.report['budget_ledger']['official_or_configured_limit_exceeded'])
        self.assertFalse(state.report['patient_understanding_assessed'])
        self.assertNotIn('TEST', [c['action'] for c in c.calls])
        return c, state.report

    def test_counterfactual_same_doctor_done_h7_executes_three_missing_actions(self):
        results = {}
        for mode in ('BASELINE', 'H7_DISABLED', 'H7'):
            c, primary = counterfactual_scenario()
            if mode == 'H7_DISABLED':
                with patch.object(GoalExecutor, 'choose', return_value=None):
                    c, r = self.run_case(client=c)
            else:
                c, r = self.run_case(client=c, strategy=mode)
            results[mode] = r
            self.assertTrue(all(p == 'DONE' for p in primary[1:]))
            if mode == 'H7':
                self.assertEqual(r['closed_loop']['supplements'], 3)
                self.assertEqual(r['action_counts'], {'SAY': 3, 'EXAM': 1})
                self.assertEqual([g['execution'] for g in r['closed_loop']['goals']], ['performed'] * 3)
                self.assertEqual([g['receipts'][0]['observation_id'] for g in r['closed_loop']['goals']], ['F3', 'F4', 'F5'])
                note = c.submissions[0]['note']
                self.assertIn('약은 먹지만 이름은 몰라요', note['S']['hpi'])
                self.assertIn('무슨 뜻인가요?', note['S']['hpi'])
                self.assertIn('복부 반발통 확인', note['O']['exam'])
                self.assertIn('[실제 SAY 설명]', note['P']['education'])
                self.assertEqual(note['O']['tests'], '')
        self.assertEqual(results['BASELINE']['actions_succeeded'], 1)
        self.assertEqual(results['H7_DISABLED']['actions_succeeded'], 1)
        self.assertEqual(results['H7']['actions_succeeded'], 4)

    def test_refused_exam_not_completed_or_retried_without_valid_revision(self):
        for reason in ('EXAM_NOT_SPECIFIC', 'EXAM_NOT_RECOGNIZED'):
            c = H7MockClient([say('언제부터인가요?'), {'action':'DONE'},
                {'goals':[goal(kind='EXAM',content='복부 반발통 확인')]}, reviewed_done, plan()], failures={'EXAM':[reason]})
            c,r=self.run_case(client=c)
            g=r['closed_loop']['goals'][0]
            self.assertEqual(g['execution'],'failed')
            self.assertEqual(g['receipts'][0]['status'],'SDK_FAILED')
            self.assertIsNone(g['receipts'][0]['observation_id'])
            self.assertEqual(sum(x['action']=='EXAM' for x in c.calls),1)
            self.assertNotIn('복부 반발통 확인',c.submissions[0]['note']['O']['exam'])

    def test_new_reply_withdraws_old_goal_and_no_stale_goal_dispatch(self):
        def invalidate(body):
            self.assertIn('지금 다른 증상이 생겼어요',body['messages'][1]['content'])
            return reviewed_done(body,needed=[],withdraw=['G1'])
        c=H7MockClient([say('언제부터인가요?'),say('지금 상태는 어떤가요?'),
            {'goals':[goal()]},invalidate,plan()], replies=['오늘','지금 다른 증상이 생겼어요'])
        c,r=self.run_case(client=c)
        self.assertEqual(r['closed_loop']['goals'][0]['execution'],'withdrawn')
        self.assertEqual(r['closed_loop']['goals'][0]['receipts'],[])
        self.assertEqual(r['closed_loop']['supplements'],0)
        self.assertNotIn('복용약을 알려주세요',c.submissions[0]['note']['S']['hpi'])

    def test_missing_or_stale_review_cannot_force_old_goal_after_new_response(self):
        for decision in ({'action':'DONE'}, {'action':'DONE','goal_review':{'revision':1,'needed':['G1']}}):
            c,r=self.run_case([say('언제부터인가요?'),say('지금 상태는 어떤가요?'),
                               {'goals':[goal()]},decision,plan()])
            self.assertEqual(r['closed_loop']['supplements'],0)
            self.assertEqual(r['closed_loop']['goals'][0]['execution'],'pending')
            self.assertEqual(r['done_decisions'][-1]['review'],'NO_FRESH_REVIEW')

    def test_partial_answer_performed_is_not_confirmed_and_can_be_clarified(self):
        def clarify(body):
            self.assertIn('약은 먹지만 이름은 몰라요',body['messages'][1]['content'])
            return reviewed_done(body,revise=[dict(id='G1',content='약 봉투가 있나요?',reason='이름이 확인되지 않음',
                condition='이름을 모르는 답변 이후',basis_ids=['F3'])])
        c=H7MockClient([say('언제부터인가요?'),{'action':'DONE'},{'goals':[goal()]},clarify,
            lambda b:reviewed_done(b,needed=[]),plan()], replies=['오늘','약은 먹지만 이름은 몰라요','없어요'])
        c,r=self.run_case(client=c)
        g=r['closed_loop']['goals'][0]
        self.assertEqual(g['version'],2)
        self.assertEqual([a['observation_id'] for a in g['receipts']],['F3','F4'])
        self.assertEqual(g['clinical_sufficiency'],'REVIEW')
        self.assertEqual(r['closed_loop']['supplements'],2)
        self.assertNotIn('약 없음',json.dumps(c.submissions[0],ensure_ascii=False))

    def test_empty_answer_is_raw_not_negative_and_not_automatically_repeated(self):
        c=H7MockClient([say('언제부터인가요?'),{'action':'DONE'},{'goals':[goal()]},reviewed_done,plan()],replies=['오늘',''])
        c,r=self.run_case(client=c)
        self.assertEqual(r['closed_loop']['supplements'],1)
        self.assertEqual(r['closed_loop']['goals'][0]['clinical_sufficiency'],'REVIEW')
        self.assertEqual(r['closed_loop']['goals'][0]['execution'],'performed')
        self.assertNotIn('복약 없음',json.dumps(c.submissions[0],ensure_ascii=False))

    def test_model_completion_claim_does_not_create_receipt(self):
        def false_claim(body):
            value=reviewed_done(body)
            value['goal_review']['completed']=['G1']
            return value
        c,r=self.run_case([say('언제부터인가요?'),say('지금 상태는 어떤가요?'),
            {'goals':[goal()]},false_claim,lambda b:reviewed_done(b,needed=[]),plan()])
        self.assertEqual(r['closed_loop']['supplements'],1)
        self.assertEqual(r['closed_loop']['goals'][0]['receipts'][0]['observation_id'],'F4')

    def test_urgent_action_bypasses_planning_and_done_override(self):
        c,r=self.run_case([say('숨쉬기는 어떤가요?',urgent=True),say('바로 도움을 요청하세요','EXPLAIN',urgent=True),
                           {'action':'DONE','urgent':True},plan()])
        self.assertEqual(r['goal_plan_events'],[])
        self.assertEqual(r['closed_loop']['supplements'],0)
        c,r=self.run_case([say('언제부터인가요?'),say('지금 상태는 어떤가요?'),{'goals':[goal()]},
            lambda b:dict(reviewed_done(b),urgent=True),plan()])
        self.assertEqual(r['closed_loop']['supplements'],0)

    def test_six_supplement_limit_is_global_even_with_seven_unperformed_goals(self):
        rows=[goal('G'+str(i),content=f'증상 {i}을 알려주세요') for i in range(1,8)]
        c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},{'goals':rows}]+[reviewed_done]*6+[plan()])
        self.assertEqual(r['closed_loop']['supplements'],6)
        self.assertEqual(r['actions_succeeded'],7)
        self.assertEqual(r['closed_loop']['goals'][-1]['execution'],'pending')
        self.assertEqual(r['termination_reason'],'DOCTOR_DONE')

    def test_sufficient_or_optional_goals_do_not_force_actions(self):
        for rows in ([],[goal(importance='optional')],[goal(currently_needed=False)]):
            c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},{'goals':rows},plan()])
            self.assertEqual(r['closed_loop']['supplements'],0)
            self.assertEqual(r['actions_succeeded'],1)
        c,r=self.run_case([{'action':'DONE'},plan()])
        self.assertEqual(r['goal_plan_events'],[])

    def test_goal_plan_failure_or_malformed_metadata_returns_baseline_path(self):
        for bad in ('not-json',TimeoutError('offline'),{'goals':'bad'}, {'goals':[goal()]*9}):
            c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},bad,plan()])
            self.assertEqual(r['actions_succeeded'],1)
            self.assertEqual(r['closed_loop']['supplements'],0)
            self.assertEqual(len(r['goal_plan_events']),1)
            self.assertEqual(r['goal_plan_events'][0]['http_attempts'],1)
            self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        c,r=self.run_case([say('언제부터인가요?'),say('지금 상태는 어떤가요?'),{'goals':[goal()]},
            {'action':'DONE','goal_review':{'revision':2,'needed':[{}]}},plan()])
        self.assertEqual(r['invalid_model_outputs'],0)

    def test_plan_parser_rejects_test_long_actions_and_nonobserved_basis(self):
        bad=[goal(kind='TEST'),goal(content='가'*31),goal(basis_ids=['REFERENCE']),goal(kind='EXAM',content='')]
        c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'}, {'goals':bad},plan()])
        self.assertEqual(r['closed_loop']['goals'],[])
        c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},
            {'goals':[goal(kind='EXAM',content='가'*30)]},reviewed_done,plan()])
        self.assertIn('가'*30,c.submissions[0]['note']['O']['exam'])

    def test_direct_action_matches_goal_only_after_ack_and_ignores_claimed_id(self):
        c,r=self.run_case([say('언제부터인가요?'),say('복용약을 알려주세요',goal_id='WRONG'),
            {'goals':[goal()]},reviewed_done,plan()])
        self.assertEqual(r['closed_loop']['supplements'],0)
        self.assertEqual(r['closed_loop']['goals'][0]['execution'],'performed')
        self.assertEqual(r['closed_loop']['goals'][0]['receipts'][0]['observation_id'],'F3')

    def test_explicit_test_cannot_be_converted_by_goal_kind_or_revision(self):
        c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},
            {'goals':[goal(kind='EXAM',content='CT',action='TEST'),goal('G2',action='TEST')]},plan()])
        self.assertEqual(r['closed_loop']['goals'],[])
        def invalid_revision(body):
            return reviewed_done(body,revise=[dict(id='G1',action='TEST',content='CT',
                reason='검사 제안',condition='현재 상태',basis_ids=['F3'])])
        c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},{'goals':[goal()]},invalid_revision,plan()])
        self.assertEqual(r['closed_loop']['supplements'],1)
        self.assertEqual(r['closed_loop']['goals'][0]['version'],1)

    def test_budget_and_time_gates_preserve_final_record(self):
        c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},plan()],max_doctor_requests=5)
        self.assertEqual(r['closed_loop']['supplements'],0)
        self.assertTrue(r['submitted'])
        # Plan can fit, but an additional ACTION + three RECORD slots cannot.
        c,r=self.run_case([say('언제부터인가요?'),{'action':'DONE'},{'goals':[goal()]},plan()],max_doctor_requests=6)
        self.assertEqual(r['closed_loop']['supplements'],0)
        with patch.object(loop.Run,'left',return_value=500):
            c,r=self.run_case([plan()])
        self.assertEqual(r['actions_succeeded'],0)
        self.assertEqual(r['termination_reason'],'TIME_MARGIN')
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')

    def test_goal_input_record_search_separation_and_per_session_reset(self):
        marker='UNPERFORMED_GOAL_PRIVATE_MARKER'
        c,r=self.run_case([say('언제부터인가요?'),say('지금 상태는 어떤가요?'),{'goals':[goal(reason=marker)]},
            lambda b:reviewed_done(b,needed=[]),plan()])
        self.assertIn(marker,c.prompts[-2][1]['content'])
        self.assertNotIn(marker,c.prompts[-1][1]['content'])
        self.assertNotIn(marker,json.dumps(c.submissions[0],ensure_ascii=False))
        for body in c.chat_bodies:
            context=json.loads(body['messages'][1]['content'])
            self.assertNotIn(marker,json.dumps(context['current_patient_observations'],ensure_ascii=False))
        c2,r2=self.run_case([{'action':'DONE'},plan()])
        self.assertEqual(r2['closed_loop']['goals'],[])

    def test_model_retry_cannot_consume_h7_final_time_margin(self):
        c=H7MockClient([plan()],failures={'CHAT':['API_UNAVAILABLE']})
        with patch.object(loop.Run,'left',side_effect=lambda:400 if c.chat_bodies else 1000):
            c,r=self.run_case(client=c)
        self.assertEqual(len(c.chat_bodies),2)  # Failed ACTION + final RECORD.
        self.assertEqual(r['actions_succeeded'],0)
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')

    def test_sdk_retry_cannot_consume_h7_final_time_margin_or_complete_goal(self):
        c=H7MockClient([say('언제부터인가요?'),{'action':'DONE'},{'goals':[goal()]},plan()],
                       failures={'SAY':[None,'API_UNAVAILABLE']})
        with patch.object(loop.Run,'left',side_effect=lambda:400 if sum(x['action']=='SAY' for x in c.calls)>=2 else 1000):
            c,r=self.run_case(client=c)
        self.assertEqual(sum(x['action']=='SAY' for x in c.calls),2)
        self.assertEqual(r['closed_loop']['goals'][0]['execution'],'failed')
        self.assertIsNone(r['closed_loop']['goals'][0]['receipts'][0]['observation_id'])
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')

    def test_failed_explanation_has_no_delivery_receipt_or_understanding_claim(self):
        c=H7MockClient([say('언제부터인가요?'),{'action':'DONE'},
            {'goals':[goal(kind='EXPLAIN',content='追加評価が必要です')]},plan()],
            failures={'SAY':[None,'API_UNAVAILABLE','API_UNAVAILABLE','API_UNAVAILABLE']})
        c,r=self.run_case(client=c)
        self.assertEqual(r['closed_loop']['goals'][0]['execution'],'failed')
        self.assertEqual(r['acknowledged_explanations'],0)
        self.assertNotIn('[실제 SAY 설명]',c.submissions[0]['note']['P']['education'])


if __name__ == '__main__':
    unittest.main()
