"""Offline strategy wiring and evidence invariants; no model-quality claims."""
import copy
import json
import os
import runpy
import unittest
from unittest.mock import patch

import nova_sdk
from nova_agent import loop, strategy_config
from nova_agent.context import fact, visible_facts
from nova_agent.prompts import STEP, RECORD
from nova_agent.strategies import action_facts, action_prompt, decision_view
from test_agent import ROOT, MockClient, NoResults, plan
from test_simple_v35 import Replies, say


class StrategyTests(unittest.TestCase):
    def test_real_entrypoint_uses_each_pinned_strategy_without_extra_calls(self):
        for strategy in ('A', 'B', 'C'):
            with self.subTest(strategy=strategy):
                c = Replies([say('약 이름을 확인할 수 있나요?'),
                             {'action': 'EXAM', 'content': '왼쪽 손목 압통 확인'},
                             say('추가 평가가 필요해요', 'EXPLAIN'), {'action': 'DONE'}, plan()],
                            ['약은 먹지만 이름은 몰라요', '무슨 뜻인가요?'])
                with patch.object(strategy_config, 'STRATEGY', strategy), \
                     patch.dict(os.environ, {'NOVA_RAG_SOURCES': 'none'}), \
                     patch.object(nova_sdk, 'Client', return_value=c):
                    runpy.run_path(str(ROOT / 'app/run.py'), run_name='__main__')
                self.assertEqual(c.chat_number, 5)
                self.assertEqual(c.prompts[0][0]['content'], action_prompt(strategy))
                self.assertEqual(json.loads(c.prompts[0][1]['content'])['decision_view']['strategy'], strategy)
                self.assertEqual(c.prompts[-1][0]['content'], RECORD)
                self.assertNotIn('decision_view', json.loads(c.prompts[-1][1]['content']))
                note = c.submissions[0]['note']
                self.assertIn('약은 먹지만 이름은 몰라요', note['S']['hpi'])
                self.assertIn('무슨 뜻인가요?', note['S']['hpi'])
                self.assertIn('이해 여부는 미확인', note['P']['education'])
                self.assertEqual(note['O']['tests'], '')
                self.assertFalse(any(x['action'] == 'TEST' for x in c.calls))

    def test_whole_latest_response_survives_context_pressure(self):
        facts = [fact('F0', 'opening', '합성 환자'), fact('F1', 'vitals', '합성 활력')]
        facts += [dict(fact(f'F{i}', 'patient_reply', '긴 답변 ' * 50, '복용약은?'), intent='ASK') for i in range(2, 15)]
        facts += [dict(fact('F15', 'patient_reply', '갑자기 숨쉬기 힘들어요', '다음 계획 안내'), intent='EXPLAIN')]
        old = copy.deepcopy(facts)
        for strategy in ('A', 'B', 'C'):
            packed = action_facts(facts, strategy, 1000)
            self.assertIn(facts[-1], packed)
            self.assertIn(facts[0], packed)
            self.assertIn(facts[1], packed)
            self.assertLessEqual(len(json.dumps(packed, ensure_ascii=False)), 1000)
            self.assertTrue(all(f in facts for f in packed))
        self.assertEqual(facts, old)

    def test_packing_priorities_are_distinct_and_no_fact_is_classified(self):
        facts = [fact('F0', 'opening', '증상'), fact('F1', 'vitals', '활력')]
        for i in range(2, 14):
            kind = 'exam' if i in (2, 3, 9) else 'patient_reply'
            facts.append(dict(fact(f'F{i}', kind, '합성 원문 ' * 30, '진찰 또는 질문'), intent='EXAM' if kind == 'exam' else 'ASK'))
        # Fit exactly four follow-up observations, so the priority boundary is exercised.
        limit = len(json.dumps(facts[:2] + facts[-4:], ensure_ascii=False))
        selections = [tuple(f['id'] for f in action_facts(facts, s, limit)) for s in ('A', 'B', 'C')]
        self.assertEqual(len(set(selections)), 3)
        for strategy in ('A', 'B', 'C'):
            selected = action_facts(facts, strategy, 22000)
            self.assertEqual(selected, facts)
            view = decision_view(selected, [{'unit_id': 'R1'}], strategy)
            self.assertEqual(view['reference_unit_ids'], ['R1'])
            self.assertNotIn('R1', view['history_reply_ids'])
            self.assertNotIn('confirmed', json.dumps(view))

    def test_record_context_and_retrieval_remain_baseline(self):
        facts = [fact('F0', 'opening', '환자 관찰'), fact('F1', 'vitals', '활력')]
        facts += [dict(fact('F2', 'patient_reply', '약은 먹고 있어요. 약 이름은 잘 모르겠어요.', '복용약은?'), intent='ASK')]
        contexts = []
        for strategy in ('baseline', 'A', 'B', 'C'):
            c = MockClient(); state = loop.State(NoResults(), strategy=strategy)
            r = loop.Run(c, state, c.session()); r.facts = copy.deepcopy(facts)
            with patch.object(loop, 'reference_packet', wraps=loop.reference_packet) as retrieval:
                action, _ = r.context(10)
                record, current = r.context(10, for_record=True)
                self.assertEqual(retrieval.call_count, 1)
                self.assertEqual(r.report['retrieval_cache_hits'], 1)
            self.assertEqual(current, visible_facts(facts))
            self.assertEqual(record, r.record_user)
            contexts.append(record)
        self.assertEqual(len(set(contexts)), 1)
        self.assertEqual(action_prompt('baseline'), STEP)

    def test_existing_format_guards_and_done_still_apply_to_each_strategy(self):
        for strategy in ('A', 'B', 'C'):
            c = MockClient([{'action': 'TEST', 'content': '혈액 검사'}, say('가' * 31),
                            say('언제 시작됐나요?'), say('언제 시작됐나요?'), {'action': 'DONE'}, plan()])
            state = loop.State(NoResults(), loop.Config(retry_delay=0), strategy=strategy)
            loop.consult(c, state)
            self.assertEqual(state.report['invalid_model_outputs'], 3)
            self.assertEqual(state.report['termination_reason'], 'DOCTOR_DONE')
            self.assertEqual(state.report['action_counts'], {'SAY': 1})
            self.assertEqual(state.report['record_outcome'], 'DOCTOR_RECORD_VALIDATED')

    def test_failed_explanation_does_not_enter_view_or_record(self):
        for strategy in ('A', 'B', 'C'):
            c = MockClient([say('추가 검사가 필요할 수 있어요', 'EXPLAIN'), plan()])
            state = loop.State(NoResults(), strategy=strategy)
            with patch.object(c, 'say', return_value={'content': '거절', 'refused': True}):
                loop.consult(c, state)
            self.assertEqual(state.report['acknowledged_explanations'], 0)
            self.assertNotIn('[실제 SAY 설명]', c.submissions[0]['note']['P']['education'])

    def test_new_turn_updates_view_without_cross_session_state(self):
        f = [fact('F0', 'opening', '증상'), fact('F1', 'vitals', '활력')]
        f.append(dict(fact('F2', 'patient_reply', '네', '추적 계획 안내'), intent='EXPLAIN'))
        view = decision_view(f, [], 'C')
        self.assertEqual(view['latest_patient_reply_id'], 'F2')
        self.assertEqual(view['dialogue_links'], [{'observation_id': 'F2', 'preceding_doctor_intent': 'EXPLAIN'}])
        self.assertNotIn('understood', json.dumps(view))
        self.assertIsNone(decision_view(f[:2], [], 'C')['latest_patient_reply_id'])
        self.assertEqual(decision_view(f, [], 'B')['executed_test_ids'], [])

    def test_invalid_selection_fails_before_calls(self):
        c = MockClient()
        with self.assertRaisesRegex(ValueError, 'INVALID_CLINICAL_STRATEGY'):
            loop.Run(c, loop.State(NoResults(), strategy='typo'), {})
        self.assertEqual(c.calls, [])
