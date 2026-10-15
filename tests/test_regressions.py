import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('NOVA_TEST_APP', str(ROOT / 'app')))
from nova_agent import prepare, consult
from nova_agent.context import fact, query_from_facts, observation_unit, reference_packet, visible_facts, evidence_candidates, UNITS
from nova_agent.policy import research_decision
from nova_agent.loop import State, Config
from nova_agent.record import render_record
from test_agent import MockClient, plan


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = prepare().index

    def test_all_106_cases_preserve_flag_but_allow_research(self):
        cases = [r for r in self.index.records if r['record_kind'] == 'coding_case']
        self.assertEqual(len(cases), 106)
        for r in cases:
            self.assertIs(r['source_metadata']['llm_processing_allowed'], False)
            self.assertTrue(research_decision(r)[0])

    def test_case_bodies_and_source_history_reach_doctor(self):
        rows = reference_packet(self.index, '당뇨 발 통증 색 변화')
        self.assertGreaterEqual(len(rows), 2)
        for r in rows:
            self.assertTrue(r['text'])
            self.assertIs(r['original_llm_processing_allowed'], False)
            self.assertEqual(r['external_submission_status'], 'UNCONFIRMED')
            self.assertTrue(r['not_current_patient_facts'])
            self.assertFalse(r['use_as_universal_diagnostic_rule'])
            self.assertTrue(r['case_id'] and r['evidence_ids'] and r['review_status'])

    def test_short_answers_include_their_questions(self):
        facts = [fact('F0', 'opening', '배가 아파요'), fact('F1','vitals','37.1'),
            fact('F2','patient_reply','네','항생제를 복용하셨나요?'),
            fact('F3','patient_reply','어제부터요','설사는 언제부터인가요?')]
        q = query_from_facts(facts)
        self.assertIn('항생제를 복용하셨나요? / 환자 답변: 네',q)
        self.assertIn('설사는 언제부터인가요? / 환자 답변: 어제부터요',q)
        self.assertIn('확인된 사실 아님',q)

    def test_negative_unknown_answers_are_verbatim(self):
        for answer in ['없어요','모르겠어요','아니요','not sure','no']:
            f = fact('F2','patient_reply',answer,'설사가 있나요?')
            q = query_from_facts([f])
            self.assertIn('환자 답변: '+answer,q)
            self.assertNotIn('설사 양성',q)
            self.assertNotIn('설사 있음',q)

    def test_exam_result_is_paired_and_negative_preserved(self):
        q = query_from_facts([fact('F2','exam','반발통 없음','복부 반발통을 확인하겠습니다')])
        self.assertIn('실제 시행한 진찰: 복부 반발통을 확인하겠습니다 / 결과: 반발통 없음',q)

    def test_unexecuted_actions_and_model_diagnoses_are_excluded(self):
        facts = [fact('F0','opening','통증'),fact('F1','proposed_exam','CT 정상'),
            fact('F2','model_diagnosis','당뇨'),fact('F3','proposed_question','항생제'),
            {**fact('F4','patient_reply','네','당뇨라고 설명'), 'intent':'EXPLAIN'}]
        q=query_from_facts(facts)
        self.assertNotIn('CT',q);self.assertNotIn('당뇨',q);self.assertNotIn('항생제',q)

    def test_budget_never_cuts_pair(self):
        facts = [fact('F0','opening','배가 아파요'),fact('F1','patient_reply','없어요','항생제 복용?'),
            fact('F2','exam','없음'*500,'복부 반발통 확인')]
        for limit in (40,100,300,1800):
            audit={};q=query_from_facts(facts,limit,audit)
            self.assertLessEqual(len(q),limit)
            for f in facts:
                if f['id'] in audit['included_ids']:
                    self.assertIn(observation_unit(f),q)
                else:
                    self.assertNotIn('['+f['id']+']',q)

    def test_early_medication_and_latest_reply_both_retained(self):
        facts=[fact('F0','opening','통증'),fact('F1','patient_reply','없어요','항생제를 복용하셨나요?')]
        facts += [fact('F'+str(i),'patient_reply', '모르겠어요' * 4, f'일상 생활 {i}번 질문') for i in range(2,42)]
        q=query_from_facts(facts,800)
        self.assertIn('항생제를 복용하셨나요? / 환자 답변: 없어요',q)
        self.assertIn('[F41]',q)
        self.assertLessEqual(len(q),800)

    def test_short_ebola_evidence_survives_long_parent(self):
        rows=reference_packet(self.index,'Ebola disease survivors viral persistence')
        docs={r['document_id']:r for r in rows}
        for did in ['00cbd2ad3feeaf0ad51da254','14f0d8248762a94cdbf4ecdf']:
            self.assertIn(did,docs)
            self.assertTrue(docs[did]['text'])
            self.assertIn(docs[did]['text_scope'],['COMPLETE_HTML_H2_WITH_NESTED_CONDITIONS','COMPLETE_MATCHED_SECTION_ENVELOPE'])
        who=docs['14f0d8248762a94cdbf4ecdf']['text']
        self.assertIn('two consecutive negative',who)
        self.assertIn('In the absence of a semen testing programme',who)
        self.assertIn('12 months',who)

    def test_heading_word_in_sentence_never_cuts_assertion(self):
        rows=reference_packet(self.index,'Ebola early dry symptoms followed four to five days later by watery diarrhea vomiting')
        source=next(r for r in rows if r['document_id']=='540845d0781514409facfe89')
        self.assertIn('Four to 5 days',source['text'])
        self.assertIn('dry',source['text'])
        self.assertIn('wet',source['text'])
        self.assertFalse(source['text'].endswith('Patients with '))
        for r in self.index.records:
            if r['record_kind']=='corrected_item':
                for u in UNITS[r['parent_id']]:
                    self.assertEqual(u['end']-u['start'],len(self.index.get_parent(r['parent_id'])['text']))

    def test_cross_heading_matched_context_has_complete_envelope(self):
        hits=self.index.search('When malaria is suspected should treatment wait for laboratory confirmation?',top_k=20,deduplicate=False)
        found=False
        for hit in hits:
            options=evidence_candidates(self.index,hit,'malaria do not delay treatment')
            envelopes=[(u,t) for u,t in options if u['scope']=='COMPLETE_MATCHED_SECTION_ENVELOPE']
            if envelopes:
                found=True
                for u,t in envelopes:
                    for uid in u['required_context']:
                        piece=next(x for x in UNITS[hit['parent_id']] if x['unit_id']==uid)
                        self.assertIn(self.index.get_parent(hit['parent_id'])['text'][piece['start']:piece['end']],t)
        self.assertTrue(found)

    def test_packet_budget_under_all_requested_limits(self):
        for budget in (128,1800,4000,8000,12000):
            for q in ['당뇨 발 통증 색 변화','Ebola disease survivors viral persistence','의사환자 검사결과가 없는']:
                audit={};rows=reference_packet(self.index,q,budget,audit=audit)
                self.assertLessEqual(len(json.dumps(rows,ensure_ascii=False)),budget)
                self.assertTrue(all(r['text'].strip() for r in rows))
                self.assertEqual(audit['valid_evidence_count'],len(rows))

    def test_blocked_or_empty_hit_does_not_consume_top_k(self):
        blocked=copy.deepcopy(self.index.records[0])
        blocked['source_metadata']['explicit_publisher_llm_prohibition']=True
        valid=copy.deepcopy(self.index.records[1])
        class Index:
            records=[blocked,valid]
            def search(self,*args,**kwargs):return self.records
            def get_parent(inner,key):return self.index.get_parent(key)
        audit={};rows=reference_packet(Index(),'복통',top_k=1,audit=audit)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['case_id'],valid['case_id'])
        self.assertEqual(audit['excluded'][0]['reason'],'PUBLISHER_RESTRICTION')

    def test_unclassified_flag_and_hash_mismatch_not_overridden(self):
        r=copy.deepcopy(self.index.records[0]);r['source_metadata']['llm_processing_restriction']='UNVERIFIED_OTHER_REASON'
        self.assertEqual(research_decision(r)[1],'UNCLASSIFIED_LEGACY_RESTRICTION')
        r=copy.deepcopy(self.index.records[0]);r['source_sha256']='wrong'
        self.assertEqual(research_decision(r)[1],'UNREVIEWED_SOURCE_OR_HASH')

    def test_unit_text_traceable_to_immutable_parent_field(self):
        for q in ['복통 항생제','Ebola survivors','당뇨 발 통증 색 변화']:
            for row in reference_packet(self.index,q):
                loc=row['unit_location'];parent=self.index.get_parent(loc['parent_id'])
                text=parent['text'] if loc['field']=='text' else parent['case_sections']['context']
                self.assertEqual(row['text'],text[loc['start']:loc['end']])
                for eid in row['evidence_ids']:
                    self.assertEqual(self.index.get_evidence(eid)['document_id'],row['document_id'])

    def test_reference_patient_tests_cannot_enter_current_note(self):
        p=plan();p['source_refs']['S']['hpi']=['case:e9c1a285d702049aef7bf70d']
        c=MockClient([{'action':'DONE'},p,p,p],opening='당뇨 발 통증 색 변화')
        state=State(self.index,Config(retry_delay=0));consult(c,state)
        note=c.submissions[-1]['note']
        self.assertEqual(note['O']['tests'],'')
        self.assertEqual(note['S']['hpi'],'')
        self.assertTrue(state.report['degraded'])
        self.assertTrue(any(r['body_chars'] for r in state.report['reference_packets']))

    def test_invalid_provider_response_regenerates_request_id(self):
        c=MockClient([{'action':'DONE'},plan()],{'CHAT':['PROVIDER_RESPONSE_INVALID',None]})
        state=State(self.index,Config(retry_delay=0));consult(c,state)
        calls=[c for c in c.calls if c['action']=='CHAT']
        self.assertNotEqual(calls[0]['request_id'],calls[1]['request_id'])
        self.assertEqual(state.report['model_retries'],1)
        self.assertEqual(state.report['doctor_unique_requests'],3)

    def test_oversized_generated_record_rejected_before_sdk(self):
        facts=[fact('F0','opening','가'*15000),fact('F1','vitals','37도')]
        p=plan()
        for f in p['source_refs']['S']:p['source_refs']['S'][f]=['F0']
        with self.assertRaisesRegex(ValueError,'RECORD_BYTE_BUDGET'):
            render_record(p,facts,[])
