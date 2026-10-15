"""Additional harness/telemetry checks, separate from the frozen 47-test suite."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'scripts'),str(ROOT/'tests')]
from sample_audit import SampleAudit
from public_samples import CountedClient,run_samples
from test_agent import MockClient,plan
import test_sample_runner
import nova_sdk


class FollowupTests(unittest.TestCase):
    def workspace(self):
        (ROOT/'validation').mkdir(parents=True,exist_ok=True)
        return tempfile.TemporaryDirectory(dir=ROOT/'validation')

    def test_local_temp_creates_only_workspace(self):
        with self.workspace() as name:
            root=Path(name)
            with patch.object(test_sample_runner,'ROOT',root):
                with test_sample_runner.local_temp() as tmp:
                    self.assertTrue(Path(tmp).is_dir())
            self.assertTrue((root/'validation').is_dir())
            self.assertFalse((root/'app').exists())

    def test_missing_inputs_are_explicit_and_not_created(self):
        with self.workspace() as name:
            missing=Path(name)/'missing_app';report=Path(name)/'output/results.json'
            result=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/run_tests.py')],capture_output=True,
                env=dict(os.environ,NOVA_TEST_APP=str(missing),NOVA_TEST_REPORT=str(report)))
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'MISSING_REQUIRED_APP_INPUTS',result.stderr)
            self.assertFalse(missing.exists());self.assertFalse(report.parent.exists())

    def test_existing_report_is_never_overwritten(self):
        with self.workspace() as name:
            report=Path(name)/'result.json';report.write_text('KEEP',encoding='utf-8')
            result=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/run_tests.py')],capture_output=True,
                env=dict(os.environ,NOVA_TEST_REPORT=str(report)))
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'KEEP_EXISTING_TEST_REPORT',result.stderr)
            self.assertEqual(report.read_text(),'KEEP')

    def test_usage_and_truncation_are_not_inferred_or_exposed(self):
        audit=SampleAudit();row=audit.chat_request({'model':'openai/gpt-6-luna','reasoning_effort':'medium','max_tokens':2048,'messages':[]})
        audit.chat_response(row,{'choices':[{'message':{'content':'PRIVATE_MODEL_RESPONSE'},'finish_reason':'length'}],
                                 'usage':{'prompt_tokens':123,'completion_tokens':2048}})
        self.assertEqual(row['usage_missing_fields'],['total_tokens'])
        self.assertTrue(row['reported_truncation']);self.assertTrue(row['output_at_requested_limit'])
        self.assertNotIn('PRIVATE_MODEL_RESPONSE',json.dumps(audit.report()))
        audit.chat_response(row,{'choices':[{'message':{'content':''}}]})
        self.assertEqual(len(row['usage_missing_fields']),3);self.assertTrue(row['empty_content'])

    def simulated_session(self,finish='stop'):
        p=plan();p['source_refs']['S']['hpi']=['F2'];p['source_refs']['O']['exam']=['F3']
        mock=MockClient([{'action':'SAY','content':'언제부터 아팠나요?'},
                         {'action':'EXAM','content':'복부 반발통 확인'},{'action':'DONE'},p])
        def transport(client,method,path,body=None):
            if path=='/v1/sample/cases':return {'cases':[{'case_id':'00000000-0000-4000-8000-000000000001'}]}
            if path=='/v1/sample/sessions':return {'session_id':'00000000-0000-4000-8000-000000000002'}
            response=mock._request(method,path,body)
            if path.endswith('/completions'):response['choices'][0]['finish_reason']=finish
            return response
        import public_samples
        from sample_ledger_fixture import approved_ledger
        with approved_ledger(public_samples) as ledger,patch.object(nova_sdk.Client,'_request',transport):
            report=run_samples(CountedClient('SYNTHETIC_NOT_A_KEY'),1,ledger=ledger)
        return report

    def test_actual_message_and_record_audit_with_mock_transport(self):
        report=self.simulated_session();row=report['cases'][0]
        self.assertEqual(report['status'],'COMPLETED_REQUESTED_PUBLIC_SAMPLES')
        self.assertTrue(row['transport_and_observation_audit_passed'])
        self.assertTrue(row['record_check']['so_matches_observed_fact_rendering'])
        self.assertEqual(row['record_check']['observation_ids'],['F0','F1','F2','F3'])
        serialized=json.dumps(report,ensure_ascii=False)
        self.assertNotIn('어제 저녁부터 시작했어요',serialized)
        self.assertNotIn('SYNTHETIC_NOT_A_KEY',serialized)
        self.assertNotIn('원인 미상 복통',serialized)

    def test_truncation_stops_additional_sessions(self):
        report=self.simulated_session('length')
        self.assertIn('STOPPED',report['status'])
        self.assertFalse(report['cases'][0]['transport_and_observation_audit_passed'])
