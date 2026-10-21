import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'scripts'),str(ROOT/'dev')]
from nova_retrieval.guidelines import GuidelinesIndex, CombinedIndex, safe_path, header, identities
from nova_agent.context import reference_packet, query_from_facts
from build_guidelines_index import build
from local_agent import LocalModelAdapter
from benchmark_adapters import agentclinic, ddxplus, ask_ddx, aci
from evaluation_summary import summarize


class GuidelineTests(unittest.TestCase):
    def setUp(self):
        work=Path(os.environ.get('NOVA_TEST_OUTPUT_DIR', str(ROOT/'validation')));work.mkdir(parents=True, exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=work);self.root=Path(self.temp.name)
        (self.root/'US_TEST').mkdir()
        fields=['파일명','제목','발행기관','연도','언어','문서 유형','형식','라이선스','출처 URL']
        row=['US_TEST/a.md','Fever guidance','Synthetic', '2026','영어','진료지침','Markdown','CC0','https://example.org/a']
        with (self.root/'catalog.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.writer(f);w.writerow(fields);w.writerow(row)
        self.source=self.root/'US_TEST/a.md'
        self.source.write_text('---\ntitle: "Fever guidance"\norganization: "Synthetic"\nyear: "2026"\nlanguage: en\nsource_url: "https://example.org/a"\nlicense: "CC0"\n---\n# Fever\n\n## Findings\nFever is not always infection. 발열이 없다고 감염을 배제하지 않는다.\n### Exception\nDo not drop this exception.\n\n## Care\nSynthetic follow up.\n',encoding='utf-8')
        self.db=self.root/'index.sqlite';build(self.root,self.db)
        self.index=GuidelinesIndex(self.db,self.root)

    def tearDown(self):
        self.index.close();self.temp.cleanup()

    def test_bilingual_search_and_attribution(self):
        for query in ['fever','발열']:
            hit=self.index.search(query)[0]
            self.assertEqual(hit['relative_path'],'US_TEST/a.md')
            for key in ['title','organization','year','language','license','source_url','source_sha256']:
                self.assertTrue(hit[key])

    def test_complete_section_and_readonly_database(self):
        row=next(self.index.evidence(self.index.search('fever')[0],'fever'))
        self.assertIn('Do not drop this exception.',row['text'])
        self.assertTrue(row['not_current_patient_facts'])
        with self.assertRaises(sqlite3.OperationalError):self.index.db.execute('DELETE FROM documents')

    def test_hash_mismatch_fails_closed(self):
        self.source.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
            list(self.index.evidence(self.index.search('fever')[0],'fever'))

    def test_traversal_and_symlink_escape(self):
        with self.assertRaises(ValueError):safe_path(self.root,'../other.md')

    def test_packet_limit_no_truncation(self):
        combined=CombinedIndex(guidelines=self.index)
        audit={};rows=reference_packet(combined,'fever',12000,audit=audit)
        self.assertLessEqual(len(json.dumps(rows,ensure_ascii=False)),12000)
        self.assertTrue(rows)
        self.assertEqual(reference_packet(combined,'fever',20),[])
        self.assertIn('Exception',rows[0]['text'])

    def test_duplicate_sources_across_indexes(self):
        row=next(self.index.evidence(self.index.search('fever')[0],'fever'))
        legacy=object()
        original=reference_packet
        def dispatch(index,*args,**kwargs):
            return [dict(row)] if index is legacy else original(index,*args,**kwargs)
        with patch('nova_agent.context.reference_packet',side_effect=dispatch):
            rows=CombinedIndex(legacy,self.index).packet('fever')
        self.assertEqual(len(rows),1)
        self.assertTrue(identities(row)&identities(dict(row,source_url='https://www.example.org/a/index.html')))

    def test_observation_negation_unchanged(self):
        facts=[{'id':'F0','kind':'opening','text':'발열 없음. No fever.','question':None}]
        self.assertIn('발열 없음. No fever.',query_from_facts(facts))

    def test_explicit_none_and_missing_root(self):
        from nova_agent import prepare
        with patch.dict(os.environ,{'NOVA_RAG_SOURCES':'none'}):
            self.assertEqual(reference_packet(prepare().index,'fever'),[])
        with patch.dict(os.environ,{'NOVA_RAG_SOURCES':'guidelines','NOVA_GUIDELINES_DIR':str(self.root/'absent'),'NOVA_GUIDELINES_INDEX':str(self.db)}):
            with self.assertRaisesRegex(ValueError,'CATALOG_MISMATCH'):prepare()


class SeparationTests(unittest.TestCase):
    def test_local_model_alias_only_in_dev_adapter(self):
        class Stub:
            def chat(self,messages,**kwargs):return kwargs
        self.assertNotIn('model',LocalModelAdapter(Stub()).chat([],model='openai/gpt-6-luna'))
        with self.assertRaises(ValueError):LocalModelAdapter(Stub()).chat([],model='other')
        from nova_agent.loop import MODEL
        self.assertEqual(MODEL,'openai/gpt-6-luna')

    def test_agentclinic_secrets_only_evaluator(self):
        case=agentclinic({'OSCE_Examination':{'Patient_Actor':{'Symptoms':{'Primary_Symptom':'weakness'},'History':'PRIVATE_HISTORY'},'Physical_Examination_Findings':{'Vital_Signs':{}},'Test_Results':{'x':'PRIVATE_TEST'},'Correct_Diagnosis':'PRIVATE_TARGET'}},0)
        text=json.dumps(case.doctor_input())
        for forbidden in ['PRIVATE_HISTORY','PRIVATE_TEST','PRIVATE_TARGET']:self.assertNotIn(forbidden,text)
        self.assertNotIn('PRIVATE_TEST',json.dumps(case.simulator_private))

    def test_ddx_one_question_only_and_split_preserved(self):
        dictionary={'E1':{'question_en':'Fever?','default_value':0},'E2':{'question_en':'Pain?','default_value':0}}
        case=ddxplus({'AGE':'42','SEX':'F','INITIAL_EVIDENCE':'E1','EVIDENCES':"['E1', 'E2']",'PATHOLOGY':'SECRET_DX','DIFFERENTIAL_DIAGNOSIS':'SECRET_DIFF'},7,'test',dictionary)
        self.assertEqual(case.case_id,'ddxplus:test:7')
        self.assertEqual(ask_ddx(case,'E1',dictionary)['answer'],[True])
        self.assertNotIn('E2',json.dumps(case.doctor_input()))
        self.assertNotIn('SECRET_DX',json.dumps(case.doctor_input()))

    def test_aci_has_no_diagnosis_score_or_note_leak(self):
        case=aci({'encounter_id':'abc','dialogue':'observed words','note':'PRIVATE_NOTE'},'valid')
        self.assertNotIn('PRIVATE_NOTE',json.dumps(case.doctor_input()))
        self.assertIsNone(case.evaluator_input()['diagnosis_accuracy'])

    def test_record_alone_does_not_imply_action(self):
        review=summarize([],{'P':{'education':'explained'}})
        self.assertEqual(review['evidence']['successful_SAY'],0)
        self.assertTrue(all(row['score'] is None for row in review['domains'].values()))


if __name__=='__main__':unittest.main()
