"""Invented dialogue fixtures, not model runs or public-sample answer keys."""
import json
import unicodedata
import unittest
from unittest.mock import patch

from nova_agent import loop
from nova_agent.consultation import DialogueState, CORE_MESSAGES
from nova_agent.context import fact, query_from_facts
from nova_agent.diagnostics import parse_action, Rejection
from nova_agent.progress import QuestionLedger
from nova_agent.record import assessment_text, render_record
from test_agent import MockClient, NoResults, plan
from test_consultation_v34 import say, explain, finish, exam


def gap(target='발병 시점'):
    return {'topic': target, 'status': 'unknown', 'priority': 'high', 'basis': ['F0'], 'reason': '진단과 다음 처치를 결정하는 데 필요'}


class NarrowRuleTests(unittest.TestCase):
    def test_specialty_names_and_single_choice_question_are_allowed(self):
        d = DialogueState()
        for text in ('내과 진료를 받으셨나요?', '소아과 진료를 받았나요?', '오전이나 오후 중 언제인가요?'):
            obj = say(text)
            d.validate(obj, parse_action(obj, set()), [fact('F0', 'opening', '합성 증상')])

    def test_disease_names_and_uncertain_judgments_are_allowed(self):
        for text in ('정상압수두증을 감별해야 함', '정상안압녹내장 감별 필요', '정상인지 확인 필요',
                     '증상이 없는지는 미확인', '발열이 없다고 단정할 수 없다', '현재는 단정하지 않고 추가 확인',
                     '증상 유무를 확인할 수 없어 추가 문진 필요', 'Normal pressure hydrocephalus is a hypothesis'):
            self.assertEqual(assessment_text(text), text)

    def test_actual_negative_predicates_still_rejected(self):
        for text in ('발열과 오한은 없음', '신경학적으로 정상이라 판단', '진찰은 정상', 'No fever or chills',
                     '다른 원인을 배제할 수 없으나 오한은 없음'):
            with self.assertRaisesRegex(ValueError, 'FREE_TEXT_FINDING_FORBIDDEN'):
                assessment_text(text)

    def test_explicit_two_questions_and_two_targets_are_rejected(self):
        d = DialogueState(); f = [fact('F0', 'opening', '합성')]
        obj = say('언제 시작했나요? 약은 먹었나요?')
        with self.assertRaisesRegex(Rejection, 'COMPOUND_QUESTION'): d.validate(obj, parse_action(obj, set()), f)
        obj = say(); obj['targets'] = ['발병 시점', '복용약']
        with self.assertRaisesRegex(Rejection, 'SINGLE_TARGET_REQUIRED'): d.validate(obj, parse_action(obj, set()), f)

    def test_nfc_limit_not_codepoint_slicing(self):
        text = '내과 진료를 받으셨나요?'
        obj = say(unicodedata.normalize('NFD', text))
        self.assertEqual(parse_action(obj, set())[1], text)
        with self.assertRaisesRegex(Rejection, 'CONTENT_OVER_30'): parse_action(say('가' * 31), set())


class AnswerProgressTests(unittest.TestCase):
    def setUp(self):
        self.d = DialogueState()
        self.facts = [fact('F0', 'opening', '새 합성 증상')]

    def add(self, text, target='발병 시점', important=False):
        f = fact('F' + str(len(self.facts)), 'patient_reply', text, '언제 시작됐나요?')
        f['intent'] = 'ASK'; self.facts.append(f)
        self.d.questions.observe(f, target, [gap(target)] if important else [])
        return f['id']

    def update(self, fid, status, quote='', remaining=''):
        return {'observation_id': fid, 'status': status, 'quote': quote, 'remaining': remaining}

    def validate(self, obj):
        return self.d.validate(obj, parse_action(obj, set()), self.facts)

    def test_received_reply_is_not_automatically_confirmed(self):
        self.add('어제부터요')
        self.assertEqual(self.d.questions.context()['goals'][0]['status'], 'received_unreviewed')

    def test_unknown_unanswered_and_unasked_are_separate(self):
        self.add('모르겠어요')
        self.add('답하고 싶지 않아요', '복용량')
        self.d.gaps = [gap('기저질환')]
        ctx = self.d.context(self.facts, 20, 900, 300)
        self.assertEqual([r['status'] for r in ctx['question_progress_not_clinical_facts']['goals']], ['unknown', 'unanswered'])
        self.assertEqual(ctx['model_proposed_gaps_not_patient_facts'][0]['question_state'], 'not_asked')

    def test_unknown_cannot_be_promoted_to_negative_or_confirmed(self):
        for text in ('몰라요', '모릅니다', '정확히 기억나지 않아요'):
            fid = self.add(text, text)
            for status in ('confirmed', 'explicit_negative'):
                with self.assertRaisesRegex(Rejection, 'ANSWER_REVIEW_OVERCLAIM'):
                    self.d.questions.validate_updates([self.update(fid, status, text)], self.facts)

    def test_partial_answer_requires_remaining_scope_and_exact_quote(self):
        fid = self.add('아침 약만 기억해요')
        with self.assertRaisesRegex(Rejection, 'INVALID_ANSWER_REVIEW'):
            self.d.questions.validate_updates([self.update(fid, 'partial', '아침 약')], self.facts)
        rows = self.d.questions.validate_updates([self.update(fid, 'partial', '아침 약', '다른 시간의 복용 여부')], self.facts)
        self.d.questions.accept(rows)
        self.assertEqual(self.d.questions.context()['goals'][0]['status'], 'partial')
        with self.assertRaisesRegex(Rejection, 'REVIEW_QUOTE_NOT_OBSERVED'):
            self.d.questions.validate_updates([self.update(fid, 'confirmed', '다른 약은 없음')], self.facts)

    def test_explicit_negative_is_reviewed_and_kept_distinct(self):
        fid = self.add('해당 약은 먹지 않아요')
        rows = self.d.questions.validate_updates([self.update(fid, 'explicit_negative', '먹지 않아요')], self.facts)
        self.d.questions.accept(rows)
        self.assertEqual(self.d.questions.context()['goals'][0]['status'], 'explicit_negative')

    def test_confirmed_goal_cannot_be_asked_again_in_same_decision(self):
        fid = self.add('어제부터요')
        obj = say('정확히 언제부터인가요?')
        obj['review']['answer_reviews'] = [self.update(fid, 'confirmed', '어제부터요')]
        with self.assertRaisesRegex(Rejection, 'QUESTION_ALREADY_CONFIRMED'): self.validate(obj)
        self.assertEqual(self.d.questions.rows[0]['status'], 'received_unreviewed')  # rejected decision is atomic

    def test_reask_requires_importance_and_stops_after_two_attempts(self):
        self.add('모르겠어요')
        obj = say('오늘 시작된 증상인가요?')
        with self.assertRaisesRegex(Rejection, 'REASK_IMPORTANCE_REQUIRED'): self.validate(obj)
        obj['review']['gaps'] = [gap()]
        self.validate(obj)
        self.add('잘 모르겠어요')
        self.assertEqual(self.d.questions.context()['goals'][0]['asked_count'], 2)
        with self.assertRaisesRegex(Rejection, 'QUESTION_REASK_LIMIT'): self.validate(obj)

    def test_important_unanswered_cannot_disappear_at_done(self):
        fid = self.add('모르겠어요', important=True)
        obj = finish(exempt=True)
        with self.assertRaises(Rejection): self.validate(obj)
        obj['review']['defer_reason'] = '정보 한계를 보존하고 대면 평가로 확인할 계획'
        self.validate(obj)
        self.assertEqual(self.d.questions.unresolved_important()[0]['observation_id'], fid)

    def test_sufficient_confirmed_information_allows_done_without_extra_question(self):
        fid = self.add('어제부터요', important=True)
        obj = finish(exempt=True)
        obj['review']['answer_reviews'] = [self.update(fid, 'confirmed', '어제부터요')]
        self.d.accept_review(self.validate(obj))
        self.assertEqual(self.d.questions.unresolved_important(), [])

    def test_invalid_review_id_cannot_import_rag_or_unexecuted_question(self):
        for fid in ('reference:1', 'F99'):
            with self.assertRaisesRegex(Rejection, 'INVALID_ANSWER_REVIEW'):
                self.d.questions.validate_updates([self.update(fid, 'confirmed', '없음')], self.facts)

    def test_ambiguous_answer_stays_unresolved(self):
        fid = self.add('그럴 수도 있어요', important=True)
        self.d.questions.accept(self.d.questions.validate_updates([self.update(fid, 'ambiguous', '그럴 수도')], self.facts))
        self.assertEqual(self.d.questions.unresolved_important()[0]['status'], 'ambiguous')


class CommunicationProgressTests(unittest.TestCase):
    def test_understanding_not_inferred_from_success_or_yes(self):
        d = DialogueState(); d.acknowledge('설명', ['plan'], 'F2', '네', '다음 계획')
        self.assertEqual(d.delivered[0]['reaction'], 'response_received_understanding_unverified')

    def test_confusion_then_response_and_repetition_are_bounded(self):
        d = DialogueState(); facts = [fact('F0', 'opening', '합성')]
        d.acknowledge('설명', ['plan'], 'F2', '무슨 뜻인지 모르겠어요', '현재 판단 설명')
        self.assertEqual(len(d.pending_feedback()), 1)
        obj = explain('다음 진료에서 함께 확인해요', ('plan',))
        d.validate(obj, parse_action(obj, set()), facts)
        d.acknowledge(obj['content'], ['plan'], 'F3', '다시 설명해 주세요', '현재 판단 설명')
        with self.assertRaisesRegex(Rejection, 'EXPLANATION_REPEAT_LIMIT'): d.validate(obj, parse_action(obj, set()), facts)
        end = finish(exempt=True)
        with self.assertRaises(Rejection): d.validate(end, parse_action(end, set()), facts)
        end['review']['communication_defer_reason'] = '추가 이해 확인은 대면 지원과 함께 진행할 계획'
        d.validate(end, parse_action(end, set()), facts)
        self.assertEqual(len(d.pending_feedback()), 1)

    def test_delivered_explanation_not_repeated_without_new_reason(self):
        d = DialogueState(); f = [fact('F0', 'opening', '합성')]
        d.acknowledge('설명', ['plan'], 'F2', '네', '현재 판단 설명')
        obj = explain(kinds=('plan',))
        with self.assertRaises(Rejection): d.validate(obj, parse_action(obj, set()), f)
        obj['new_explanation_reason'] = '환자의 새로운 질문에 맞춰 범위를 구체화'
        d.validate(obj, parse_action(obj, set()), f)

    def test_no_response_does_not_mean_understood(self):
        d = DialogueState(); d.acknowledge('설명', ['safety'], 'F2', '', '주의사항')
        self.assertEqual(d.pending_feedback()[0]['reaction'], 'no_response')
        self.assertNotIn('safety', d.missing_messages())  # delivered and understood are separate

    def test_different_topic_does_not_clear_earlier_confusion(self):
        d = DialogueState()
        d.acknowledge('첫 설명', ['plan'], 'F2', '무슨 뜻인가요?', '진료 계획')
        d.acknowledge('둘째 설명', ['plan'], 'F3', '네', '예약 방법')
        self.assertEqual([r['observation_id'] for r in d.pending_feedback()], ['F2'])

    def test_clearer_response_is_still_not_certified_understanding(self):
        d = DialogueState()
        d.acknowledge('첫 설명', ['plan'], 'F2', '무슨 뜻인가요?', '진료 계획')
        d.acknowledge('쉬운 설명', ['plan'], 'F3', '네', '진료 계획')
        self.assertEqual(d.pending_feedback(), [])
        self.assertEqual(d.delivered[-1]['reaction'], 'response_received_understanding_unverified')


class RuntimeProgressTests(unittest.TestCase):
    def test_cache_reuses_same_query_but_new_patient_reply_invalidates(self):
        c = MockClient(); s = loop.State(NoResults(), loop.Config(consultation_review=True))
        r = loop.Run(c, s, c.session()); r.facts = [fact('F0', 'opening', '합성 증상')]
        with patch.object(loop, 'reference_packet', wraps=loop.reference_packet) as retrieve:
            r.context(30); r.context(29)
            r.facts.append(fact('F1', 'patient_reply', '네', '설명'))
            r.facts[-1]['intent'] = 'EXPLAIN'; r.context(28)
            self.assertEqual(retrieve.call_count, 1)
            r.facts.append(fact('F2', 'patient_reply', '어제 새 약을 먹었어요', '설명'))
            r.facts[-1]['intent'] = 'EXPLAIN'; r.context(27)
            self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(r.report['retrieval_cache_hits'], 2)
        self.assertNotIn('의사 설명 자체', query_from_facts(r.facts))
        other = loop.Run(c, s, c.session())
        self.assertIsNone(other.reference_cache)

    def test_explanation_text_never_becomes_retrieval_observation(self):
        f = fact('F2', 'patient_reply', '새 약을 먹었어요', '의사 설명 자체의 가상 진단')
        f['intent'] = 'EXPLAIN'
        query = query_from_facts([f])
        self.assertIn('새 약을 먹었어요', query)
        self.assertNotIn('가상 진단', query)

    def test_actual_flow_unknown_reask_exam_and_acknowledged_explanation(self):
        first = say(); first['review']['gaps'] = [gap()]
        second = say('오늘 시작됐는지 기억나나요?'); second['review']['gaps'] = [gap()]
        physical = exam(); physical['review']['answer_reviews'] = [{'observation_id': 'F3', 'status': 'confirmed', 'quote': '어제부터요'}]
        end = finish()
        class Replies(MockClient):
            def __init__(self, outputs):
                super().__init__(outputs); self.replies = iter(['모르겠어요', '어제부터요', '네'])
            def say(self, *args, **kwargs):
                result = super().say(*args, **kwargs); result['content'] = next(self.replies); return result
        c = Replies([first, second, physical, explain('합성 평가 계획과 주의를 안내해요', CORE_MESSAGES), end, plan()])
        s = loop.State(NoResults(), loop.Config(consultation_review=True, retry_delay=0))
        loop.consult(c, s)
        self.assertTrue(s.report['successful_execution'])
        self.assertEqual(s.report['action_counts'], {'SAY': 3, 'EXAM': 1})
        self.assertEqual(s.report['consultation_review']['answer_status_counts'], {'confirmed': 1})
        self.assertFalse(s.report['budget_ledger']['official_or_configured_limit_exceeded'])
        note = c.submissions[0]['note']
        self.assertIn('모르겠어요', note['S']['hpi']); self.assertIn('어제부터요', note['S']['hpi'])
        self.assertIn('관찰 결과', note['O']['exam']); self.assertIn('[실제 SAY 설명]', note['P']['education'])
        self.assertEqual(note['O']['tests'], '')

    def test_failed_ask_does_not_create_answer_progress(self):
        c = MockClient([say(), plan()], failures={'SAY': ['API_UNAVAILABLE'] * 3})
        s = loop.State(NoResults(), loop.Config(consultation_review=True, retry_delay=0))
        loop.consult(c, s)
        self.assertEqual(s.report['consultation_review']['answer_status_counts'], {})
        self.assertEqual(s.report['observed_fact_count'], 2)

    def test_record_preserves_unknown_and_negative_without_completing_unanswered(self):
        facts = [fact('F0', 'opening', '합성'), fact('F1', 'vitals', '합성 활력징후'),
                 fact('F2', 'patient_reply', '모르겠어요', '이전에 복용한 적 있나요?'),
                 fact('F3', 'patient_reply', '해당 약은 안 먹어요', '현재 이 약을 먹나요?')]
        note, _ = render_record(plan(), facts, [])
        self.assertIn('모르겠어요', note['S']['hpi']); self.assertIn('해당 약은 안 먹어요', note['S']['hpi'])
        self.assertNotIn('복용력 없음', json.dumps(note, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
