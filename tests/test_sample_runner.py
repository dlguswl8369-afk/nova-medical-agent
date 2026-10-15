import importlib.util
import json
import tempfile
from contextlib import contextmanager
import unittest
from pathlib import Path
from types import SimpleNamespace
from sample_ledger_fixture import approved_ledger

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sample_runner',ROOT/'scripts/public_samples.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

@contextmanager
def local_temp():
    work = ROOT/'validation'
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        assert Path(tmp).resolve().is_relative_to(work.resolve())
        yield tmp

class Client:
    http_attempts=0
    last_record_check={'sdk_validation_passed':True}
    def __init__(self):self.created=[]
    def _request(self,*a):
        self.http_attempts+=1
        return {'cases':[{'case_id':str(i)} for i in range(10)]}
    def create_sample(self,case_id,**kwargs):
        self.http_attempts+=1;self.created.append(case_id)

def success(client,state):
    state.report={'submitted':True,'successful_execution':True,'diagnosis_unresolved':False,
        'reference_packets':[{'body_chars':100}], 'action_counts':{'SAY':1,'EXAM':1}}

class SampleRunnerTests(unittest.TestCase):
    def test_three_max_including_rerun(self):
        with approved_ledger(runner) as ledger:
            c=Client()
            r=runner.run_samples(c,1,ledger=ledger,prepare_fn=lambda:SimpleNamespace(report={}),consult_fn=success)
            self.assertEqual(len(c.created),1)
            self.assertEqual(r['status'],'COMPLETED_REQUESTED_PUBLIC_SAMPLES')
            c=Client()
            with self.assertRaises(runner.NovaError):
                runner.run_samples(c,1,ledger=ledger,prepare_fn=lambda:SimpleNamespace(report={}),consult_fn=success)
            self.assertEqual(c.created,[])
            self.assertEqual(len(json.loads(ledger.read_text())['attempts']),3)
    def test_first_failure_stops_expansion(self):
        with approved_ledger(runner) as ledger:
            c=Client()
            r=runner.run_samples(c,1,ledger=ledger,prepare_fn=lambda:SimpleNamespace(report={}),consult_fn=lambda c,s:None)
            self.assertEqual(len(c.created),1)
            self.assertIn('STOPPED',r['status'])
    def test_transport_failure_still_consumes_session_budget(self):
        class Broken(Client):
            def create_sample(self,*a,**k):raise runner.NovaError('API_UNAVAILABLE')
        with approved_ledger(runner) as ledger:
            runner.run_samples(Broken(),1,ledger=ledger,prepare_fn=lambda:SimpleNamespace(report={}),consult_fn=success)
            self.assertEqual(len(json.loads(ledger.read_text())['attempts']),3)
    def test_no_reference_or_no_exam_does_not_expand(self):
        def incomplete(c,s):
            success(c,s);s.report['reference_packets']=[]
        with approved_ledger(runner) as ledger:
            c=Client();runner.run_samples(c,1,ledger=ledger,prepare_fn=lambda:SimpleNamespace(report={}),consult_fn=incomplete)
            self.assertEqual(len(c.created),1)
