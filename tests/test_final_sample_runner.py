"""Only synthetic ledgers and clients. No real token, session or network access."""
import contextlib
import io
import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import public_samples as runner
from sample_ledger_fixture import approved_ledger

class FakeClient:
    last_record_check={'synthetic':True}
    def __init__(self):self.http_attempts=0;self.created=[]
    def _request(self,*args):
        self.http_attempts+=1
        return {'cases':[{'case_id':'synthetic-third'},{'case_id':'never-create-fourth'}]}
    def create_sample(self,case_id,**kwargs):
        self.http_attempts+=1;self.created.append((case_id,kwargs['request_id']))

def success(client,state):
    state.report={'submitted':True,'successful_execution':True,'diagnosis_unresolved':False,
        'reference_packets':[{'body_chars':100}],'action_counts':{'SAY':1,'EXAM':1}}

def run(client,path,**kwargs):
    return runner.run_samples(client,ledger=path,prepare_fn=lambda:SimpleNamespace(report={}),consult_fn=success,**kwargs)

class FinalSampleTests(unittest.TestCase):
    def test_two_to_three_then_rerun_blocked_before_http(self):
        with approved_ledger(runner) as path:
            old=runner.read_ledger(path)['attempts'];c=FakeClient();report=run(c,path)
            new=runner.read_ledger(path)['attempts']
            self.assertEqual(report['status'],'COMPLETED_REQUESTED_PUBLIC_SAMPLES')
            self.assertEqual(new[:2],old);self.assertEqual(len(new),3);self.assertEqual(len(c.created),1)
            self.assertEqual(c.created[0][1],new[-1]['request_id'])
            again=FakeClient()
            with self.assertRaisesRegex(runner.NovaError,'LOCAL_FINAL_SAMPLE_ALREADY_ATTEMPTED'):run(again,path)
            self.assertEqual(again.http_attempts,0)

    def test_each_full_existing_record_and_order_are_anchored(self):
        for index in (0,1):
            for field in ('case_id','request_id','time','extra'):
                with self.subTest(index=index,field=field),approved_ledger(runner) as path:
                    data=runner.read_ledger(path);data['attempts'][index][field]='modified'
                    path.write_text(json.dumps(data),encoding='utf-8');before=path.read_bytes()
                    with self.assertRaisesRegex(runner.NovaError,'LOCAL_SESSION_LEDGER_HISTORY_CHANGED'):
                        runner.reserve_session(path,'never')
                    self.assertEqual(path.read_bytes(),before)
        with approved_ledger(runner) as path:
            data=runner.read_ledger(path);data['attempts'].reverse();path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(runner.NovaError,'LOCAL_SESSION_LEDGER_HISTORY_CHANGED'):runner.check_shared_ledger(path)

    def test_identical_copy_other_path_rejected(self):
        with approved_ledger(runner) as path:
            copy=path.with_name('copied.json');copy.write_bytes(path.read_bytes())
            with self.assertRaisesRegex(runner.NovaError,'LOCAL_WRONG_SHARED_LEDGER'):run(FakeClient(),copy)
            self.assertEqual(len(runner.read_ledger(path)['attempts']),2)

    def test_missing_ledger_not_created(self):
        with approved_ledger(runner) as path:
            path.unlink()
            with self.assertRaises(FileNotFoundError):runner.reserve_session(path,'never')
            self.assertFalse(path.exists());self.assertFalse(path.with_suffix('.lock').exists())

    def test_legacy_anchor_is_not_a_fallback(self):
        with approved_ledger(runner) as path:
            auth=runner.ROOT/'reports/final_sample_authorization.json'
            auth.rename(auth.with_name('session_ledger_anchor.json'))
            with self.assertRaises(FileNotFoundError):run(FakeClient(),path)

    def test_zero_or_one_prior_attempt_is_rejected(self):
        for count in (0,1):
            with approved_ledger(runner) as path:
                data=runner.read_ledger(path);data['attempts']=data['attempts'][:count]
                path.write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises(runner.NovaError):run(FakeClient(),path)

    def test_no_generic_initializer_or_unbounded_mode(self):
        with approved_ledger(runner) as path:
            for expected in (None,0,1,3):
                with self.assertRaisesRegex(runner.NovaError,'LOCAL_INVALID_EXPECTED_ATTEMPTS'):
                    runner.reserve_session(path,'never',expected_attempts=expected)
            for count in (0,2,3):
                with self.assertRaisesRegex(runner.NovaError,'LOCAL_ONE_ADDITIONAL_SAMPLE_ONLY'):
                    run(FakeClient(),path,max_samples=count)
            self.assertEqual(len(runner.read_ledger(path)['attempts']),2)

    def test_explicit_failure_does_not_refund(self):
        class Broken(FakeClient):
            def create_sample(self,*a,**kw):raise runner.NovaError('API_UNAVAILABLE')
        with approved_ledger(runner) as path:
            report=run(Broken(),path)
            self.assertEqual(report['cases'][0]['failure_code'],'API_UNAVAILABLE')
            self.assertEqual(len(runner.read_ledger(path)['attempts']),3)
            with self.assertRaises(runner.NovaError):run(FakeClient(),path)

    def test_uncertain_timeout_does_not_refund_or_export_exception(self):
        class TimedOut(FakeClient):
            def create_sample(self,*a,**kw):raise TimeoutError('PRIVATE_TRANSPORT_DATA')
        with approved_ledger(runner) as path:
            report=run(TimedOut(),path)
            self.assertEqual(report['cases'][0]['failure_code'],'LOCAL_TRANSPORT_UNCERTAIN')
            self.assertEqual(len(runner.read_ledger(path)['attempts']),3)
            self.assertNotIn('PRIVATE_TRANSPORT_DATA',json.dumps(report))

    def test_concurrent_runs_only_one_can_reach_http(self):
        entered=threading.Event();release=threading.Event();errors=[]
        class Waiting(FakeClient):
            def _request(self,*args):
                entered.set()
                if not release.wait(5):raise AssertionError('TEST_SYNCHRONIZATION_TIMEOUT')
                return super()._request(*args)
        with approved_ledger(runner) as path:
            first=Waiting();second=FakeClient()
            def target():
                try:run(first,path)
                except Exception as exc:errors.append(type(exc).__name__)
            worker=threading.Thread(target=target);worker.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(runner.NovaError,'LOCAL_SAMPLE_RUN_LOCKED'):run(second,path)
                self.assertEqual(second.http_attempts,0)
            finally:release.set();worker.join(5)
            self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
            self.assertEqual(len(first.created),1);self.assertEqual(len(runner.read_ledger(path)['attempts']),3)
            self.assertFalse(path.with_suffix('.run.lock').exists())

    def test_concurrent_reservations_only_one_write(self):
        entered=threading.Event();release=threading.Event();errors=[]
        real_replace=runner.os.replace
        def waiting_replace(src,dst):
            entered.set()
            if not release.wait(5):raise AssertionError('TEST_SYNCHRONIZATION_TIMEOUT')
            return real_replace(src,dst)
        with approved_ledger(runner) as path,patch.object(runner.os,'replace',waiting_replace):
            def target():
                try:runner.reserve_session(path,'synthetic-third')
                except Exception as exc:errors.append(type(exc).__name__)
            worker=threading.Thread(target=target);worker.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(runner.NovaError,'LOCAL_SESSION_LEDGER_LOCKED'):
                    runner.reserve_session(path,'never-fourth')
            finally:release.set();worker.join(5)
            self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
            self.assertEqual(len(runner.read_ledger(path)['attempts']),3)

    def test_stale_locks_and_pending_are_not_automatically_deleted(self):
        for suffix in ('.run.lock','.lock','.pending'):
            with approved_ledger(runner) as path:
                blocked=path.with_suffix(suffix);blocked.write_text('SYNTHETIC_INCOMPLETE',encoding='utf-8')
                if suffix=='.run.lock':
                    with self.assertRaises(runner.NovaError):run(FakeClient(),path)
                elif suffix=='.lock':
                    with self.assertRaises(runner.NovaError):runner.reserve_session(path,'never')
                else:
                    with self.assertRaises(FileExistsError):runner.reserve_session(path,'never')
                self.assertTrue(blocked.exists());self.assertEqual(len(runner.read_ledger(path)['attempts']),2)

    def test_readonly_preflight_never_reads_key_or_makes_client(self):
        with approved_ledger(runner) as path:
            before=path.read_bytes()
            with patch.object(runner.sys,'argv',['public_samples.py','--ledger',str(path),'--check-ledger']), \
                    patch.object(runner.os,'getenv',side_effect=AssertionError('KEY_READ_FORBIDDEN')), \
                    patch.object(runner,'CountedClient') as client,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(),0);client.assert_not_called()
            self.assertEqual(path.read_bytes(),before)

    def test_main_passes_two_prior_attempts_and_one_sample(self):
        with approved_ledger(runner) as path:
            fake=SimpleNamespace(http_attempts=0,counts={},confirmed_sample_sessions=0,transport_diagnostics=[])
            with patch.object(runner.sys,'argv',['public_samples.py','--ledger',str(path),'--max-samples','1']), \
                    patch.object(runner.os,'getenv',return_value='SYNTHETIC_NOT_A_KEY'), \
                    patch.dict(runner.os.environ,{'NOVA_DEV_KEY':'SYNTHETIC_NOT_A_KEY'}), \
                    patch.object(runner,'CountedClient',return_value=fake), \
                    patch.object(runner,'run_samples',return_value={'status':'SYNTHETIC_ONLY','cases':[]}) as call, \
                    contextlib.redirect_stdout(io.StringIO()):
                runner.main()
                self.assertEqual(call.call_args.kwargs['expected_attempts'],2)
                self.assertEqual(call.call_args.args[1],1)
            self.assertEqual(len(runner.read_ledger(path)['attempts']),2)

if __name__=='__main__':unittest.main()
