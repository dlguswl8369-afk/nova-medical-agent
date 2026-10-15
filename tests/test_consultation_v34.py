"""Failure-pattern regressions using invented fixtures, no public case answers."""
import copy
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'tests')]
import nova_sdk
from nova_agent import loop
from nova_agent.consultation import DialogueState, CORE_MESSAGES
from nova_agent.context import fact
from nova_agent.diagnostics import parse_action, Rejection
from nova_agent.action_repair import MARKER
from nova_agent.record import render_record, assessment_text
from nova_agent.prompts import STEP_V34, RECORD
from test_agent import MockClient, NoResults, plan


def review(**extra):
    return dict(answered=[], gaps=[], **extra)


def say(text='언제 시작했나요?', **extra):
    return dict(action='SAY', content=text, intent='ASK', targets=['발병 시점'],
                purpose='경과에 따라 다음 확인을 선택', review=review(), **extra)


def explain(text='아직 원인을 확정하기 어려워요', kinds=('uncertainty',)):
    obj = say(text)
    obj.update(intent='EXPLAIN', targets=['현재 판단 설명'], communication=list(kinds))
    return obj


def finish(exempt=False):
    data = review(ready_to_close=True, done_reason='현재 확보 자료로 다음 단계를 판단')
    if exempt:
        data['not_applicable'] = {k: '합성 단위 테스트에서 추가 설명 적응증 없음' for k in CORE_MESSAGES}
    return {'action': 'DONE', 'review': data}


def exam():
    obj = say('오른쪽 발목 압통을 확인합니다')
    obj.update(action='EXAM', targets=['발목 압통'])
    return obj


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.dialogue = DialogueState()
        self.facts = [fact('F0', 'opening', '새로 생긴 합성 통증')]

    def validate(self, obj):
        return self.dialogue.validate(obj, parse_action(obj, set()), self.facts)

    def test_compound_partial_reply_is_not_a_negative_for_every_item(self):
        self.facts.append(fact('F1', 'patient_reply', '기침은 하지 않아요', '기침이나 오한이 있나요?'))
        state = self.dialogue.context(self.facts, 20, 1000, 300)
        self.assertEqual(state['observations'][1]['answer_scope'], 'POSSIBLY_PARTIAL_REPLY')
        self.assertNotIn('negative', json.dumps(state['observations']))
        with self.assertRaisesRegex(Rejection, 'COMPOUND_QUESTION'):
            self.validate(say('기침 있나요? 오한도 있나요?'))

    def test_unknown_reply_stays_unknown(self):
        self.facts.append(fact('F1', 'patient_reply', '정확히 기억이 안 나요', '복용량은 얼마인가요?'))
        self.assertEqual(self.dialogue.context(self.facts, 20, 1000, 300)['observations'][1]['answer_scope'], 'PATIENT_UNCERTAIN')

    def test_only_exact_observation_quote_not_question_or_reference(self):
        self.facts.append(fact('F1', 'patient_reply', '기침은 하지 않아요', '오한도 있나요?'))
        obj = say()
        obj['review']['answered'] = [{'fact_id': 'F1', 'quote': '오한도'}]
        with self.assertRaisesRegex(Rejection, 'REVIEW_QUOTE_NOT_OBSERVED'): self.validate(obj)
        obj['review']['answered'] = [{'fact_id': 'reference:1', 'quote': '정상'}]
        with self.assertRaisesRegex(Rejection, 'INVALID_REVIEW_OBSERVATION'): self.validate(obj)
        obj['review']['answered'] = [{'fact_id': 'F1', 'quote': '기침은 하지 않아요'}]
        self.dialogue.accept_review(self.validate(obj))
        self.assertEqual(self.dialogue.reviewed['F1'], ['기침은 하지 않아요'])

    def test_model_gap_is_not_confirmed_patient_fact(self):
        obj = say()
        obj['review']['gaps'] = [{'topic': '상황별 위험', 'status': 'ambiguous', 'priority': 'high', 'basis': ['F0'], 'reason': '답변 범위 재확인 필요'}]
        self.dialogue.accept_review(self.validate(obj))
        ctx = self.dialogue.context(self.facts, 10, 1000, 300)
        self.assertEqual(ctx['model_proposed_gaps_not_patient_facts'][0]['status'], 'ambiguous')
        self.assertEqual(len(self.facts), 1)

    def test_malformed_review_types_fail_as_validation_not_crash(self):
        for row in ({'fact_id': [], 'quote': 'x'}, {'fact_id': None, 'quote': 'x'}):
            obj = say(); obj['review']['answered'] = [row]
            with self.assertRaises(Rejection): self.validate(obj)
        for field, value in [('gaps', {}), ('answered', 'yes')]:
            obj = say(); obj['review'][field] = value
            with self.assertRaises(Rejection): self.validate(obj)

    def test_one_target_and_one_exam(self):
        obj = say(); obj['targets'] = ['증상', '시작']
        with self.assertRaisesRegex(Rejection, 'SINGLE_TARGET_REQUIRED'): self.validate(obj)
        obj = exam(); obj['content'] = '발목을 촉진하고 무릎을 관찰합니다'
        with self.assertRaisesRegex(Rejection, 'COMPOUND_EXAM'): self.validate(obj)
        self.validate(exam())

    def test_planned_explanation_does_not_count_as_delivered(self):
        self.dialogue.accept_review(self.validate(explain()))
        self.assertEqual(self.dialogue.delivered, [])
        with self.assertRaisesRegex(Rejection, 'DONE_WITHOUT_COMMUNICATION'): self.validate(finish())

    def test_missing_information_requires_explicit_ending_review(self):
        obj = finish(exempt=True); obj['review']['ready_to_close'] = False
        with self.assertRaisesRegex(Rejection, 'PREMATURE_DONE'): self.validate(obj)
        obj = finish(exempt=True); obj['review']['gaps'] = [{'topic': '새 위험', 'status': 'unknown', 'priority': 'high', 'basis': ['F0'], 'reason': '확인 필요'}]
        with self.assertRaises(Rejection): self.validate(obj)
        obj['review']['defer_reason'] = '추가 문진보다 즉시 평가 연결이 필요하다는 판단'
        self.validate(obj)

    def test_case_specific_exemption_is_not_fabricated_say(self):
        self.dialogue.accept_review(self.validate(finish(exempt=True)))
        self.assertEqual(self.dialogue.delivered, [])
        self.assertEqual(set(self.dialogue.last_review['not_applicable']), set(CORE_MESSAGES))

    def test_close_phase_is_conditional_and_high_risk_can_take_priority(self):
        self.assertEqual(self.dialogue.context(self.facts, 25, 1200, 300)['phase'], 'COLLECT')
        self.assertEqual(self.dialogue.context(self.facts, 3, 1200, 300)['phase'], 'CLOSE')
        with self.assertRaisesRegex(Rejection, 'CLOSING_COMMUNICATION_REQUIRED'): self.validate(say())
        obj = say(); obj['review']['gaps'] = [{'topic': '새 위험', 'status': 'unknown', 'priority': 'high', 'basis': ['F0'], 'reason': '현재 위해 여부 확인'}]
        self.validate(obj)
        self.dialogue = DialogueState()
        self.assertEqual(self.dialogue.context(self.facts, 25, 1200, 300, budget_low=True)['phase'], 'CLOSE')

    def test_no_fixed_examination_or_explanation_count(self):
        self.dialogue.acknowledge('합성 설명', list(CORE_MESSAGES), 'F1')
        self.validate(finish())
        self.assertEqual(len(self.dialogue.delivered), 1)


class RuntimeTests(unittest.TestCase):
    def run_case(self, outputs, failures=None, client_type=MockClient, **config):
        c = client_type(outputs, failures, opening='합성 통증에 대해 상담하고 싶어요')
        s = loop.State(NoResults(), loop.Config(consultation_review=True, retry_delay=0, **config))
        with patch.object(socket, 'socket', side_effect=AssertionError('NETWORK_DISABLED')), patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NETWORK_DISABLED')):
            loop.consult(c, s)
        self.assertTrue(s.report['submitted'])
        self.assertFalse(s.report['budget_ledger']['official_or_configured_limit_exceeded'])
        self.assertFalse(any(row['action'] == 'TEST' for row in c.calls))
        return c, s.report

    def test_full_flow_acknowledged_explanations_and_record(self):
        outputs = [say(), exam(), explain(), explain('다음 진료에서 원인을 확인해요', ('plan',)), explain('갑자기 심해지면 바로 진료받으세요', ('safety',)), finish(), plan()]
        c, r = self.run_case(outputs)
        self.assertTrue(r['successful_execution'])
        self.assertEqual(r['consultation_review']['acknowledged_explanations'], 3)
        self.assertEqual(r['consultation_review']['undelivered_categories'], [])
        self.assertIn('어제 저녁', c.submissions[0]['note']['S']['hpi'])
        self.assertIn('관찰 결과', c.submissions[0]['note']['O']['exam'])
        self.assertIn('갑자기 심해지면', c.submissions[0]['note']['P']['education'])
        first = json.loads(c.prompts[0][1]['content'])
        self.assertEqual(first['doctor_explanations_already_sent'], [])
        last = json.loads(c.prompts[-1][1]['content'])
        self.assertEqual(len(last['doctor_explanations_already_sent']), 3)

    def test_missing_review_is_repaired_not_silently_accepted(self):
        c, r = self.run_case([{'action': 'DONE'}, finish(exempt=True), plan()])
        self.assertEqual(r['rejection_events'][0]['reason'], 'CONSULTATION_REVIEW_REQUIRED')
        self.assertEqual(r['actions_succeeded'], 0)

    def test_premature_done_replaced_by_explicit_model_explanation(self):
        c, r = self.run_case([finish(), explain('합성 평가와 주의사항을 안내해요', CORE_MESSAGES), finish(), plan()])
        self.assertEqual(r['rejection_events'][0]['reason'], 'DONE_WITHOUT_COMMUNICATION')
        self.assertEqual(r['consultation_review']['acknowledged_explanations'], 1)

    def test_repeated_31_character_failure_uses_tighter_target_without_slicing(self):
        def repaired(body):
            payload = json.loads(body['messages'][1]['content'].split(MARKER)[1])
            self.assertEqual(payload['actual_nfc_chars'], 31)
            self.assertEqual(payload['target_chars'], [12, 18])
            for required in ('review', 'targets', 'purpose', 'communication', 'ready_to_close'):
                self.assertIn(required, payload['schema'])
            self.assertLessEqual(len((MARKER + json.dumps(payload, ensure_ascii=False)).encode('utf-8')), 4096)
            return say('통증은 언제 시작됐나요?')
        c, r = self.run_case([say('가' * 31), say('나' * 31), repaired, finish(exempt=True), plan()])
        self.assertEqual([x['content_chars'] for x in r['rejection_events']], [31, 31])
        self.assertEqual(r['actions_succeeded'], 1)
        self.assertNotIn('가' * 30, json.dumps(c.submissions, ensure_ascii=False))
        self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')

    def test_persistent_format_failure_still_stops_with_record_reserve(self):
        c, r = self.run_case([say('가' * 31)] * 3 + [plan()])
        self.assertEqual(r['termination_reason'], 'LOCAL_ACTION_FORMAT_RETRIES_EXHAUSTED')
        self.assertEqual(r['final_http_attempts'], 1)
        self.assertFalse(r['successful_execution'])

    def test_invalid_json_and_forbidden_test_never_turn_into_exam(self):
        c, r = self.run_case(['{bad', {'action': 'TEST', 'content': '검사'}, finish(exempt=True), plan()])
        self.assertEqual(r['actions_succeeded'], 0)
        self.assertEqual([x['reason'] for x in r['rejection_events']], ['JSON_PARSE_FAILED', 'ACTION_NOT_ALLOWED'])

    def test_failed_or_refused_say_never_counts_as_explanation(self):
        class Refused(MockClient):
            def say(self, *args, **kwargs):
                return {'content': '거절 응답', 'refused': True, 'turns_remaining': 49}
        c, r = self.run_case([explain(), plan()], client_type=Refused)
        self.assertEqual(r['consultation_review']['acknowledged_explanations'], 0)
        self.assertNotIn('[실제 SAY 설명]', c.submissions[0]['note']['P']['education'])
        self.assertEqual(r['termination_reason'], 'ACTION_NOT_ACKNOWLEDGED')

    def test_same_id_retry_counts_one_acknowledged_say(self):
        c, r = self.run_case([explain('합성 평가 설명입니다', CORE_MESSAGES), finish(), plan()], failures={'SAY': ['API_UNAVAILABLE', None]})
        calls = [x for x in c.calls if x['action'] == 'SAY']
        self.assertEqual(calls[0]['request_id'], calls[1]['request_id'])
        self.assertEqual(r['consultation_review']['acknowledged_explanations'], 1)

    def test_exhausted_say_retries_do_not_create_patient_fact(self):
        c, r = self.run_case([explain(), plan()], failures={'SAY': ['API_UNAVAILABLE'] * 3})
        self.assertEqual(r['observed_fact_count'], 2)
        self.assertEqual(r['consultation_review']['acknowledged_explanations'], 0)

    def test_call_budget_releases_communication_buffer_in_close_phase(self):
        c, r = self.run_case([finish(exempt=True), plan()], max_doctor_requests=4)
        self.assertEqual(json.loads(c.prompts[0][1]['content'])['consultation_state']['phase'], 'CLOSE')
        self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
        self.assertLessEqual(r['doctor_http_attempts'], 4)

    def test_record_negative_inference_is_rejected_then_repaired(self):
        bad = plan(); bad['differential'] = [{'text': '기침과 오한이 없어 다른 원인 고려', 'fact_ids': ['F0']}]
        c, r = self.run_case([finish(exempt=True), bad, plan()])
        self.assertEqual(r['rejection_events'][0]['reason'], 'FREE_TEXT_FINDING_FORBIDDEN')
        self.assertNotIn('오한이 없어', c.submissions[0]['note']['A']['differential'])
        self.assertEqual(r['final_http_attempts'], 2)

    def test_production_prepare_and_real_entrypoint_enable_new_protocol(self):
        c = MockClient([finish(exempt=True), plan()])
        with patch.dict(os.environ, {'NOVA_RAG_SOURCES': 'none'}), patch.object(nova_sdk, 'Client', return_value=c), patch.object(socket, 'socket', side_effect=AssertionError('NETWORK_DISABLED')):
            self.assertTrue(loop.prepare().config.consultation_review)
            runpy.run_path(str(ROOT / 'app/run.py'), run_name='__main__')
        self.assertIn('consultation_state', json.loads(c.prompts[0][1]['content']))
        self.assertEqual(c.prompts[0][0]['content'], STEP_V34)
        self.assertEqual(c.calls[0]['path'], '/_nova/ready')
        self.assertEqual(c.calls[-1]['action'], 'DIAGNOSE')

    def test_aggregate_report_does_not_export_patient_or_model_text(self):
        c, r = self.run_case([say('비공개합성표식 질문'), finish(exempt=True), plan()])
        rendered = json.dumps(r, ensure_ascii=False)
        self.assertNotIn('비공개합성표식', rendered)
        self.assertNotIn('합성 통증에 대해', rendered)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.facts = [fact('F0', 'opening', '새 합성 증상'), fact('F1', 'vitals', '합성 활력징후'),
            fact('F2', 'patient_reply', '약물 알레르기는 없어요', '약물 알레르기가 있나요?'),
            fact('F3', 'exam', '국소 압통 확인', '오른쪽 발목 압통 확인')]

    def test_omitted_reply_and_performed_exam_are_retained_without_new_claims(self):
        note, _ = render_record(plan(), self.facts, [])
        self.assertIn('[F2]', note['S']['hpi'])
        self.assertIn('약물 알레르기는 없어요', note['S']['hpi'])
        self.assertIn('[F3]', note['O']['exam'])
        self.assertNotIn('정상', note['O']['exam'])

    def test_vitals_deduplicated_by_id_and_selected_reply_not_duplicated(self):
        p = plan(); p['source_refs']['O']['exam'] = ['F1', 'F3']; p['source_refs']['S']['pmh'] = ['F2']
        note, _ = render_record(p, self.facts, [])
        self.assertEqual(note['O']['exam'].count('[F1]'), 1)
        self.assertEqual('\n'.join(note['S'].values()).count('[F2]'), 1)

    def test_partial_reply_does_not_generate_other_negative_findings(self):
        self.facts[2] = fact('F2', 'patient_reply', '기침은 안 해요', '기침이나 오한이 있나요?')
        p = plan(); p['assessment'] = [{'text': '기침과 오한 호소는 없음', 'fact_ids': ['F2']}]
        with self.assertRaisesRegex(ValueError, 'FREE_TEXT_FINDING_FORBIDDEN'): render_record(p, self.facts, [])
        p['assessment'] = [{'text': '추가 문진으로 원인 확인 필요', 'fact_ids': ['F2']}]
        note, _ = render_record(p, self.facts, [])
        self.assertIn('환자 답변: 기침은 안 해요', note['S']['hpi'])
        self.assertNotIn('오한 호소는 없음', json.dumps(note, ensure_ascii=False))

    def test_cautious_hypothesis_is_allowed_but_new_normal_prose_is_not(self):
        assessment_text('다른 원인을 배제할 수 없어 추가 확인 필요')
        for text in ('신경학적으로 정상이라 추정', 'No fever or chills', '다른 증상 부인'):
            with self.assertRaisesRegex(ValueError, 'FREE_TEXT_FINDING_FORBIDDEN'): assessment_text(text)

    def test_planned_education_not_promoted_to_actual_explanation(self):
        p = plan(); p['plans']['education'] = '위험 증상 안내 예정'
        note, _ = render_record(p, self.facts, [])
        self.assertIn('[계획; 시행 여부 미확인]', note['P']['education'])
        self.assertNotIn('[실제 SAY 설명]', note['P']['education'])

    def test_new_information_in_reply_to_explanation_is_not_lost(self):
        extra = fact('F4', 'patient_reply', '사실 어제 약을 추가로 먹었어요', '약 복용은 확인 후 결정해요')
        extra['intent'] = 'EXPLAIN'
        note, _ = render_record(plan(), self.facts + [extra], ['약 복용은 확인 후 결정해요'])
        self.assertIn('환자 답변: 사실 어제 약을 추가로 먹었어요', note['S']['hpi'])
        self.assertIn('실제 설명:', note['S']['hpi'])


if __name__ == '__main__':
    unittest.main()
