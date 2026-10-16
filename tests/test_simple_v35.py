"""Synthetic protocol regressions; no clinical-quality or score assertions."""
import json
import os
import runpy
import unittest
import unicodedata
from unittest.mock import patch

import nova_sdk
from nova_agent import loop
from nova_agent.action_repair import MARKER
from nova_agent.context import fact, query_from_facts
from nova_agent.diagnostics import parse_action, Rejection
from nova_agent.prompts import STEP
from nova_agent.record import render_record, fallback_record
from test_agent import ROOT, MockClient, NoResults, plan


def say(content='언제 시작됐나요?', intent='ASK', **extra):
    return dict(action='SAY', content=content, intent=intent, **extra)


class Replies(MockClient):
    def __init__(self, outputs, replies, **kwargs):
        super().__init__(outputs, **kwargs)
        self.replies = iter(replies)

    def say(self, **kwargs):
        result = super().say(**kwargs)
        result['content'] = next(self.replies)
        return result


class SimpleFlowTests(unittest.TestCase):
    def run_case(self, client, **config):
        state = loop.State(NoResults(), loop.Config(retry_delay=0, **config))
        loop.consult(client, state)
        self.assertTrue(state.report['submitted'])
        self.assertFalse(state.report['budget_ledger']['official_or_configured_limit_exceeded'])
        self.assertFalse(any(c['action'] == 'TEST' for c in client.calls))
        return state.report

    def test_question_exam_explanation_done_need_no_metadata(self):
        c = MockClient([say(), {'action': 'EXAM', 'content': '왼쪽 발목 압통 확인'},
                        say('추가 평가가 필요해요', 'EXPLAIN'), {'action': 'DONE'}, plan()])
        r = self.run_case(c)
        self.assertEqual(r['action_counts'], {'SAY': 2, 'EXAM': 1})
        self.assertEqual(r['invalid_model_outputs'], 0)
        self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')
        self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
        self.assertTrue(r['successful_execution'])
        self.assertEqual(r['acknowledged_explanations'], 1)
        note = c.submissions[0]['note']
        self.assertIn('문진 질문:', note['S']['hpi'])
        self.assertIn('관찰 결과:', note['O']['exam'])
        self.assertIn('[실제 SAY 설명]', note['P']['education'])

    def test_done_does_not_require_explanations_or_exemptions(self):
        c = MockClient([{'action': 'DONE'}, plan()])
        r = self.run_case(c)
        self.assertEqual(r['doctor_http_attempts'], 2)
        self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')
        self.assertEqual(r['acknowledged_explanations'], 0)
        self.assertEqual(r['invalid_model_outputs'], 0)

    def test_mixed_reply_no_longer_requires_status_or_rejects_confirmed_quote(self):
        mixed = '약은 먹고 있어요. 약 이름은 잘 모르겠어요.'
        for extra in ({}, {'review': {'answer_reviews': [{'observation_id': 'F2',
                      'status': 'confirmed', 'quote': '약은 먹고 있어요.'}]},
                      'targets': ['약 이름'], 'purpose': '약 확인'}):
            with self.subTest(metadata=bool(extra)):
                c = Replies([say('약을 복용하고 있나요?', targets=['약 복용 여부']),
                             say('약 봉투로 확인할 수 있나요?', **extra),
                             {'action': 'DONE'}, plan()], [mixed, '지금은 없어요'])
                r = self.run_case(c)
                self.assertEqual(r['invalid_model_outputs'], 0)
                self.assertEqual(r['actions_succeeded'], 2)
                self.assertIn(mixed, c.submissions[0]['note']['S']['hpi'])
                self.assertNotIn('복용약 없음', json.dumps(c.submissions, ensure_ascii=False))

    def test_optional_goal_status_and_importance_cannot_block_actions(self):
        extras = {'review': {'answered': 'obsolete', 'gaps': [{'priority': 'routine'}]},
                  'targets': [], 'purpose': None, 'communication': []}
        c = MockClient([say(**extras), {'action': 'EXAM', 'content': '왼쪽 발목 압통 확인', **extras},
                        say('다음 진료에서 확인해요', 'EXPLAIN', **extras),
                        {'action': 'DONE', **extras}, plan()])
        r = self.run_case(c)
        self.assertEqual(r['invalid_model_outputs'], 0)
        self.assertEqual(r['actions_succeeded'], 3)
        self.assertNotIn('obsolete', c.prompts[-1][1]['content'])

    def test_reasking_is_not_blocked_by_goal_name_or_attempt_count(self):
        outputs = [say(t, targets=['복용약']) for t in
                   ('약 이름이 무엇인가요?', '약 봉투가 있나요?', '약 사진을 확인할 수 있나요?')]
        c = Replies(outputs + [{'action': 'DONE'}, plan()], ['모르겠어요', '잘 모르겠어요', '네'])
        r = self.run_case(c)
        self.assertEqual(r['actions_succeeded'], 3)
        self.assertEqual(r['invalid_model_outputs'], 0)

    def test_three_tags_do_not_prove_safety_or_understanding(self):
        text = '추가 검사가 필요할 수 있어요.'
        c = Replies([say(text, 'EXPLAIN', communication=['uncertainty', 'plan', 'safety']),
                     {'action': 'DONE'}, plan()], ['네'])
        r = self.run_case(c)
        context = json.loads(c.prompts[-1][1]['content'])
        self.assertEqual(context['doctor_explanations_already_sent'], [text])
        self.assertNotIn('consultation_state', context)
        self.assertNotIn('missing_messages', context)
        self.assertNotIn('safety', json.dumps(context))
        self.assertNotIn('acknowledged_categories', r)
        self.assertEqual(r['acknowledged_explanations'], 1)
        self.assertFalse(r['patient_understanding_assessed'])
        self.assertIn('이해 여부는 미확인', c.submissions[0]['note']['P']['education'])

    def test_confusion_and_empty_reply_preserved_without_forced_continuation(self):
        for reply in ('무슨 뜻인가요?', '', '네'):
            with self.subTest(reply=reply):
                c = Replies([say('추가 평가가 필요해요', 'EXPLAIN'), {'action': 'DONE'}, plan()], [reply])
                r = self.run_case(c)
                ctx = json.loads(c.prompts[-1][1]['content'])
                observation = ctx['current_patient_observations'][-1]
                self.assertEqual(observation['text'], reply)
                self.assertEqual(observation['intent'], 'EXPLAIN')
                self.assertFalse(r['patient_understanding_assessed'])
                self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')

    def test_explanations_have_no_fixed_tag_count_or_repeat_limit(self):
        texts = ['진료에서 함께 확인해요', '검사 필요성을 상담해요', '궁금한 점을 말씀해 주세요']
        c = Replies([say(t, 'EXPLAIN', targets=['계획'], communication=['plan']) for t in texts]
                    + [{'action': 'DONE'}, plan()], ['무슨 뜻인가요?', '다시 설명해 주세요', '네'])
        r = self.run_case(c)
        self.assertEqual(r['acknowledged_explanations'], 3)
        self.assertEqual(r['invalid_model_outputs'], 0)
        self.assertIn('무슨 뜻인가요?', c.submissions[0]['note']['S']['hpi'])

    def test_refused_or_malformed_say_is_not_delivered(self):
        responses = [{'content': '거절', 'refused': True}, {'content': '거절', 'status': 'REFUSED'},
                     {'content': '오류', 'error': 'SYNTHETIC'}, {'content': 1},
                     {'content': '응답', 'turns_remaining': True}]
        for response in responses:
            with self.subTest(response=response):
                c = MockClient([say('추가 평가가 필요해요', 'EXPLAIN'), plan()])
                with patch.object(c, 'say', return_value=response):
                    r = self.run_case(c)
                self.assertEqual(r['acknowledged_explanations'], 0)
                self.assertEqual(r['observed_fact_count'], 2)
                self.assertNotIn('[실제 SAY 설명]', c.submissions[0]['note']['P']['education'])

    def test_exhausted_say_retries_do_not_create_observations(self):
        c = MockClient([say('추가 평가가 필요해요', 'EXPLAIN'), plan()],
                       failures={'SAY': ['API_UNAVAILABLE'] * 3})
        r = self.run_case(c)
        self.assertEqual(r['acknowledged_explanations'], 0)
        self.assertEqual(r['observed_fact_count'], 2)

    def test_successful_retry_records_one_explanation_after_acknowledgment(self):
        c = MockClient([say('추가 평가가 필요해요', 'EXPLAIN'), {'action': 'DONE'}, plan()],
                       failures={'SAY': ['API_UNAVAILABLE', None]})
        r = self.run_case(c)
        calls = [x for x in c.calls if x['action'] == 'SAY']
        self.assertEqual(calls[0]['request_id'], calls[1]['request_id'])
        self.assertEqual(r['acknowledged_explanations'], 1)
        self.assertEqual(json.loads(c.prompts[0][1]['content'])['doctor_explanations_already_sent'], [])
        self.assertEqual(len(json.loads(c.prompts[-1][1]['content'])['doctor_explanations_already_sent']), 1)

    def test_prior_specialty_false_positives_are_sent(self):
        c = MockClient([say('내과 진료를 받으셨나요?'), say('소아과 진료를 받았나요?'),
                        {'action': 'DONE'}, plan()])
        r = self.run_case(c)
        self.assertEqual(r['actions_succeeded'], 2)
        self.assertEqual(r['invalid_model_outputs'], 0)

    def test_repeated_length_error_tightens_target_without_review_schema(self):
        def repaired(body):
            payload = json.loads(body['messages'][1]['content'].split(MARKER)[1])
            self.assertEqual(payload['actual_nfc_chars'], 31)
            self.assertEqual(payload['target_chars'], [12, 18])
            for field in ('review', 'targets', 'purpose', 'communication', 'ready_to_close'):
                self.assertNotIn(field, payload['schema'])
            return say('통증은 언제 시작됐나요?')
        c = MockClient([say('가' * 31), say('나' * 31), repaired, {'action': 'DONE'}, plan()])
        r = self.run_case(c)
        self.assertEqual([e['content_chars'] for e in r['rejection_events']], [31, 31])
        self.assertEqual(r['actions_succeeded'], 1)
        self.assertNotIn('가' * 30, json.dumps(c.submissions, ensure_ascii=False))

    def test_nfc_and_repeat_guards_remain(self):
        text = '내과 진료를 받으셨나요?'
        self.assertEqual(parse_action(say(unicodedata.normalize('NFD', text)), set())[1], text)
        with self.assertRaisesRegex(Rejection, 'CONTENT_OVER_30'):
            parse_action(say('가' * 31), set())
        with self.assertRaisesRegex(Rejection, 'REPEATED_ACTION'):
            parse_action(say(text), {('SAY', text)})

    def test_done_and_fallback_are_reported_separately(self):
        c = MockClient([{'action': 'DONE'}, 'bad', 'bad', 'bad'])
        r = self.run_case(c)
        self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')
        self.assertEqual(r['record_outcome'], 'LOCAL_OBSERVATION_ONLY_FALLBACK')
        self.assertTrue(r['submitted'])
        self.assertFalse(r['successful_execution'])

    def test_final_record_reserve_without_communication_buffer(self):
        c = MockClient([{'action': 'DONE'}, plan()])
        r = self.run_case(c, max_doctor_requests=4)
        self.assertEqual(r['termination_reason'], 'DOCTOR_DONE')
        self.assertEqual(r['record_outcome'], 'DOCTOR_RECORD_VALIDATED')
        self.assertEqual(r['action_record_headrooms'][0]['reserved_calls'], 3)

    def test_production_prepare_and_entrypoint_use_simple_flow(self):
        c = MockClient([say(), {'action': 'EXAM', 'content': '왼쪽 발목 압통 확인'},
                        say('추가 평가가 필요해요', 'EXPLAIN'), {'action': 'DONE'}, plan()])
        with patch.dict(os.environ, {'NOVA_RAG_SOURCES': 'none'}), patch.object(nova_sdk, 'Client', return_value=c):
            runpy.run_path(str(ROOT / 'app/run.py'), run_name='__main__')
        self.assertEqual(c.prompts[0][0]['content'], STEP)
        self.assertNotIn('consultation_state', json.loads(c.prompts[0][1]['content']))
        self.assertEqual(c.calls[0]['path'], '/_nova/ready')
        self.assertEqual(c.calls[-1]['action'], 'DIAGNOSE')
        self.assertEqual(c.chat_number, 5)

    def test_reports_do_not_export_patient_or_model_text(self):
        c = Replies([say('비공개합성표식 질문'), {'action': 'DONE'}, plan()], ['비공개합성표식 답변'])
        r = self.run_case(c)
        self.assertNotIn('비공개합성표식', json.dumps(r, ensure_ascii=False))


class CacheTests(unittest.TestCase):
    def test_same_query_reused_new_patient_information_retrieved(self):
        c = MockClient(); s = loop.State(NoResults())
        r = loop.Run(c, s, c.session()); r.facts = [fact('F0', 'opening', '합성 증상')]
        with patch.object(loop, 'reference_packet', wraps=loop.reference_packet) as retrieve:
            r.context(30); r.context(29)
            r.facts.append(dict(fact('F1', 'patient_reply', '네', '의사 설명'), intent='EXPLAIN'))
            r.context(28)
            self.assertEqual(retrieve.call_count, 1)
            r.facts.append(dict(fact('F2', 'patient_reply', '어제 새 약을 먹었어요', '의사 설명'), intent='EXPLAIN'))
            r.context(27)
            self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(r.report['retrieval_cache_hits'], 2)
        self.assertIsNone(loop.Run(c, s, c.session()).reference_cache)

    def test_only_immediately_previous_query_cached(self):
        c = MockClient(); r = loop.Run(c, loop.State(NoResults()), c.session())
        with patch.object(loop, 'query_from_facts', side_effect=['one', 'two', 'one', 'one']), \
             patch.object(loop, 'reference_packet', wraps=loop.reference_packet) as retrieve:
            for _ in range(4): r.context(20)
        self.assertEqual(retrieve.call_count, 3)
        self.assertEqual(r.report['retrieval_cache_hits'], 1)

    def test_cache_packet_not_aliased_to_returned_context(self):
        c = MockClient(); r = loop.Run(c, loop.State(NoResults()), c.session())
        original = [{'unit_id': 'reference:one', 'evidence_ids': ['source'], 'document_id': 'ref', 'text': '본문'}]
        def retrieve(index, query, limit, audit):
            audit['excluded'] = []
            return original
        with patch.object(loop, 'reference_packet', side_effect=retrieve):
            first, _ = r.context(20)
            original[0]['text'] = 'changed outside cache'
            second, _ = r.context(19)
        self.assertEqual(json.loads(first)['reference_evidence'], json.loads(second)['reference_evidence'])

    def test_doctor_explanation_not_retrieved_as_patient_fact(self):
        f = dict(fact('F2', 'patient_reply', '새 약을 먹었어요', '의사 설명 자체의 가상 진단'), intent='EXPLAIN')
        query = query_from_facts([f])
        self.assertIn('새 약을 먹었어요', query)
        self.assertNotIn('가상 진단', query)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.facts = [fact('F0', 'opening', '새 합성 증상'), fact('F1', 'vitals', '합성 활력징후'),
                      fact('F2', 'patient_reply', '약물 알레르기는 없어요', '약물 알레르기가 있나요?'),
                      fact('F3', 'exam', '국소 압통 확인', '오른쪽 발목 압통 확인')]

    def test_omitted_reply_and_performed_exam_are_retained(self):
        note, _ = render_record(plan(), self.facts, [])
        self.assertIn('[F2]', note['S']['hpi'])
        self.assertIn('약물 알레르기는 없어요', note['S']['hpi'])
        self.assertIn('[F3]', note['O']['exam'])
        self.assertNotIn('정상', note['O']['exam'])

    def test_vitals_deduplicated_and_selected_reply_not_duplicated(self):
        p = plan(); p['source_refs']['O']['exam'] = ['F1', 'F3']; p['source_refs']['S']['pmh'] = ['F2']
        note, _ = render_record(p, self.facts, [])
        self.assertEqual(note['O']['exam'].count('[F1]'), 1)
        self.assertEqual('\n'.join(note['S'].values()).count('[F2]'), 1)

    def test_partial_and_unknown_answers_preserved_without_synthesized_negatives(self):
        for answer in ('기침은 안 해요', '모르겠어요', '약은 먹고 있어요. 약 이름은 잘 모르겠어요.'):
            with self.subTest(answer=answer):
                facts = self.facts + [fact('F4', 'patient_reply', answer, '합성 질문의 일부를 확인해요?')]
                for renderer in (lambda: render_record(plan(), facts, []), lambda: fallback_record(facts, [])):
                    note, _ = renderer()
                    self.assertIn('문진 질문: 합성 질문의 일부를 확인해요?', note['S']['hpi'])
                    self.assertIn('환자 답변: ' + answer, note['S']['hpi'])
                    self.assertNotIn('오한 없음', json.dumps(note, ensure_ascii=False))
                    self.assertNotIn('복용력 없음', json.dumps(note, ensure_ascii=False))

    def test_observed_negative_and_normal_findings_allowed_in_assessment(self):
        self.facts[2]['text'] = '발열은 없어요'
        self.facts[3]['text'] = '정상 소견'
        p = plan(); p['assessment'] = [{'text': '발열 없음은 현재 답변에 근거함', 'fact_ids': ['F2']},
                                       {'text': '진찰은 정상 소견이나 원인 추가 확인 필요', 'fact_ids': ['F3']}]
        note, _ = render_record(p, self.facts, [])
        self.assertIn('발열 없음', note['A']['evidence'])
        self.assertIn('정상 소견', note['A']['evidence'])

    def test_disease_names_and_uncertain_hypotheses_allowed(self):
        p = plan()
        for text in ('정상압수두증을 감별해야 함', '정상안압녹내장 감별 필요', '다른 원인을 배제할 수 없음'):
            p['differential'] = [{'text': text, 'fact_ids': ['F0']}]
            note, _ = render_record(p, self.facts, [])
            self.assertIn(text, note['A']['differential'])

    def test_assessment_still_requires_actual_observation_ids(self):
        for ids in ([], ['reference:one'], ['F99']):
            p = plan(); p['assessment'] = [{'text': '추가 확인 필요', 'fact_ids': ids}]
            with self.assertRaises(ValueError): render_record(p, self.facts, [])

    def test_plan_does_not_count_as_delivered_education(self):
        p = plan(); p['plans']['education'] = '위험 증상 안내 예정'
        note, _ = render_record(p, self.facts, [])
        self.assertIn('[계획; 시행 여부 미확인]', note['P']['education'])
        self.assertNotIn('[실제 SAY 설명]', note['P']['education'])

    def test_new_information_after_explanation_preserved_in_record(self):
        extra = dict(fact('F4', 'patient_reply', '사실 어제 약을 추가로 먹었어요', '약 복용은 확인 후 결정해요'), intent='EXPLAIN')
        note, _ = render_record(plan(), self.facts + [extra], ['약 복용은 확인 후 결정해요'])
        self.assertIn('환자 답변: 사실 어제 약을 추가로 먹었어요', note['S']['hpi'])
        self.assertIn('실제 설명:', note['S']['hpi'])


if __name__ == '__main__':
    unittest.main()
