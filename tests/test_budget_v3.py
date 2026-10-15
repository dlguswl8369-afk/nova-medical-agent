"""Synthetic accounting/telemetry regressions; never contact a provider."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'app'), str(ROOT/'scripts'), str(ROOT/'tests')]
from nova_agent.budget import Budget, usage_pair
from nova_agent.diagnostics import parse_object, parse_action, rejection_event
from nova_agent.loop import Run, Config, State
from nova_agent import prepare, consult
from nova_sdk import NovaError
from test_agent import MockClient, plan
import public_samples as runner


class BudgetTests(unittest.TestCase):
    def budget(self, i=500000, o=100000, c=200):
        return Budget(i, o, c)

    def reserve(self, b, rid='one', i=10000, o=2048, **kwargs):
        b.reserve(rid, i, o, 'same-payload', **kwargs)

    def test_actual_settlement_releases_only_this_reservation(self):
        b=self.budget();self.reserve(b);self.reserve(b,'uncertain')
        b.settle('one',{'prompt_tokens':3000,'completion_tokens':150,'total_tokens':3150})
        self.assertEqual(b.totals(),([3000,150],[10000,2048]))
        self.assertEqual(b.summary()['committed_input'],13000)

    def test_missing_partial_invalid_usage_retains_both_dimensions(self):
        values=[None,{},[],{'prompt_tokens':10},{'completion_tokens':4},
            {'prompt_tokens':True,'completion_tokens':2},{'prompt_tokens':1.5,'completion_tokens':2},
            {'prompt_tokens':-1,'completion_tokens':2},{'prompt_tokens':'10','completion_tokens':2},
            {'prompt_tokens':10,'completion_tokens':None},
            {'prompt_tokens':10,'completion_tokens':2,'total_tokens':99},
            {'prompt_tokens':10,'completion_tokens':2,'total_tokens':True}]
        for usage in values:
            with self.subTest(usage=usage):
                b=self.budget();self.reserve(b);b.settle('one',usage)
                self.assertEqual(b.totals(),([0,0],[10000,2048]))
                self.assertEqual(b.invalid_usage_responses,1)

    def test_complete_pair_without_optional_total_is_usable(self):
        self.assertEqual(usage_pair({'prompt_tokens':10,'completion_tokens':0}),(10,0))

    def test_uncertain_request_keeps_reservation(self):
        b=self.budget();self.reserve(b)
        self.assertEqual(b.summary()['uncertain_reserved_input'],10000)

    def test_same_id_retry_no_double_reservation(self):
        b=self.budget();self.reserve(b);self.reserve(b)
        self.assertEqual(b.summary()['committed_input'],10000)
        self.assertEqual(b.http_attempts,2);self.assertEqual(len(b.requests),1)
        b.settle('one',{'prompt_tokens':100,'completion_tokens':20})
        self.assertEqual(b.totals(),([100,20],[0,0]))

    def test_duplicate_response_never_refunds_twice(self):
        b=self.budget();self.reserve(b)
        usage={'prompt_tokens':100,'completion_tokens':20}
        b.settle('one',usage);b.settle('one',usage)
        self.assertEqual(b.summary()['committed_input'],100)
        self.assertEqual(b.duplicate_responses,1)

    def test_same_id_with_different_content_is_rejected(self):
        b=self.budget();self.reserve(b)
        with self.assertRaises(NovaError) as c:b.reserve('one',10000,2048,'different')
        self.assertEqual(c.exception.code,'LOCAL_REQUEST_ID_CONTENT_MISMATCH')
        self.assertEqual(b.http_attempts,1)

    def test_new_id_regeneration_separately_charged(self):
        b=self.budget();self.reserve(b);self.reserve(b,'two')
        b.settle('two',{'prompt_tokens':200,'completion_tokens':20})
        self.assertEqual(b.totals(),([200,20],[10000,2048]))

    def test_actual_above_estimate_is_not_clamped(self):
        b=self.budget(i=1000,o=100);self.reserve(b,i=100,o=10)
        b.settle('one',{'prompt_tokens':1100,'completion_tokens':120})
        self.assertEqual(b.summary()['committed_input'],1100)
        self.assertTrue(b.summary()['official_or_configured_limit_exceeded'])
        with self.assertRaises(NovaError):self.reserve(b,'two',i=1,o=1)
        self.assertEqual(b.http_attempts,1)

    def test_input_boundary(self):
        b=self.budget(i=100);self.reserve(b,i=100)
        with self.assertRaises(NovaError):self.reserve(b,'two',i=1)
        self.assertEqual(len(b.requests),1)

    def test_output_boundary(self):
        b=self.budget(o=10);self.reserve(b,o=10)
        with self.assertRaises(NovaError):self.reserve(b,'two',o=1)
        self.assertEqual(b.summary()['committed_output'],10)

    def test_calls_count_same_id_retries_conservatively(self):
        b=self.budget(c=2);self.reserve(b);self.reserve(b)
        with self.assertRaises(NovaError):self.reserve(b)
        self.assertEqual(b.http_attempts,2)

    def test_final_headroom_is_not_charged_usage(self):
        b=self.budget(i=310000)
        self.reserve(b,headroom=(300000,12288,3))
        self.assertEqual(b.summary()['committed_input'],10000)
        with self.assertRaises(NovaError):self.reserve(b,'two',i=1,headroom=(300000,12288,3))
        self.assertEqual(b.last_proposal['final_headroom_calls'],3)
        self.assertFalse(b.last_proposal['allowed'])
        self.reserve(b,'final1',i=100000,o=4096)
        self.reserve(b,'final2',i=100000,o=4096)
        self.reserve(b,'final3',i=100000,o=4096)
        self.assertEqual(b.summary()['committed_input'],310000)

    def test_conflicting_duplicates_do_not_free_reservations(self):
        b=self.budget();self.reserve(b)
        b.settle('one',{'prompt_tokens':100,'completion_tokens':20})
        b.settle('one',{'prompt_tokens':90,'completion_tokens':10})
        b.settle('one',{'prompt_tokens':11000,'completion_tokens':50})
        self.assertEqual(b.totals(),([0,0],[11000,2048]))
        self.assertEqual(b.conflicting_responses,1)

    def test_invalid_duplicate_does_not_clear_confirmed_usage(self):
        b=self.budget();self.reserve(b);b.settle('one',{'prompt_tokens':100,'completion_tokens':20})
        b.settle('one',None)
        self.assertEqual(b.totals(),([100,20],[0,0]))


class LoopV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.index=prepare().index

    def run_case(self, client, **options):
        state=State(self.index,Config(retry_delay=0,**options));consult(client,state);return state.report

    def test_loop_normal_usage_settles(self):
        r=self.run_case(MockClient([{'action':'DONE'},plan()]))
        self.assertEqual(r['budget_ledger']['confirmed_input'],600)
        self.assertEqual(r['budget_ledger']['uncertain_reserved_input'],0)
        self.assertEqual(r['termination_reason'],'DOCTOR_DONE')
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')

    def test_transport_uncertainty_retained_then_settled_on_same_id(self):
        r=self.run_case(MockClient([{'action':'DONE'},plan()],{'CHAT':['API_UNAVAILABLE',None]}))
        b=r['budget_ledger'];self.assertEqual(b['unique_requests'],2)
        self.assertEqual(b['http_attempts'],3);self.assertEqual(b['confirmed_input'],600)
        self.assertEqual(b['uncertain_reserved_input'],0)
        self.assertEqual(b['requests'][0]['attempts'],2)

    def test_unresolved_outage_keeps_each_unique_reservation(self):
        r=self.run_case(MockClient(failures={'CHAT':['API_UNAVAILABLE']*6}))
        self.assertEqual(r['budget_ledger']['unique_requests'],2)
        self.assertGreater(r['budget_ledger']['uncertain_reserved_input'],0)
        self.assertEqual(r['budget_ledger']['confirmed_input'],0)
        self.assertEqual(r['termination_kind'],'EXECUTION_ERROR')

    def test_timeout_during_response_body_retains_unknown_reservations(self):
        class TimedOut(MockClient):
            def chat(self,*args,**kwargs):raise TimeoutError('PRIVATE_TRANSPORT_DETAIL')
        r=self.run_case(TimedOut())
        self.assertEqual(r['doctor_http_attempts'],6)
        self.assertEqual(r['budget_ledger']['unique_requests'],2)
        self.assertGreater(r['budget_ledger']['uncertain_reserved_input'],0)
        self.assertNotIn('PRIVATE_TRANSPORT_DETAIL',json.dumps(r))

    def test_invalid_provider_new_id_keeps_old_unknown_usage(self):
        r=self.run_case(MockClient([{'action':'DONE'},plan()],{'CHAT':['PROVIDER_RESPONSE_INVALID',None]}))
        self.assertEqual(r['budget_ledger']['unique_requests'],3)
        self.assertGreater(r['budget_ledger']['uncertain_reserved_input'],0)
        self.assertEqual(r['budget_ledger']['confirmed_input'],600)

    def test_budget_stop_is_expected_and_final_call_preserved(self):
        r=self.run_case(MockClient(),max_doctor_requests=1)
        self.assertEqual(r['termination_kind'],'EXPECTED_LIMIT')
        self.assertEqual(r['termination_reason'],'LOCAL_MODEL_BUDGET')
        self.assertEqual(r['doctor_http_attempts'],1)
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        self.assertTrue(r['submitted'])

    def test_final_transport_plus_format_retry_total_never_exceeds_three(self):
        c=MockClient([{'action':'DONE'},'bad','bad','bad'],{'CHAT':[None,'API_UNAVAILABLE',None]})
        r=self.run_case(c)
        self.assertEqual(r['final_http_attempts'],3)
        self.assertEqual(r['record_failure_reason'],'LOCAL_FINAL_RETRY_BUDGET')
        self.assertEqual(r['record_outcome'],'LOCAL_OBSERVATION_ONLY_FALLBACK')

    def test_action_reasons_are_distinct_and_text_not_exported(self):
        cases=[('not json','JSON_PARSE_FAILED'),('[]','OBJECT_REQUIRED'),
            ({'action':'TEST'},'ACTION_NOT_ALLOWED'),({'action':'SAY','content':[]},'CONTENT_TYPE'),
            ({'action':'SAY','content':'  '},'EMPTY_CONTENT'),
            ({'action':'SAY','content':'x'*31},'CONTENT_OVER_30'),
            ({'action':'SAY','content':'private-question','intent':'INVALID'},'INVALID_INTENT')]
        for bad,code in cases:
            with self.subTest(code=code):
                r=self.run_case(MockClient([bad,{'action':'DONE'},plan()]))
                self.assertEqual(r['rejection_events'][0]['reason'],code)
                self.assertNotIn('private-question',json.dumps(r))
        with self.assertRaises(ValueError) as caught:
            parse_action({'action':'SAY','content':'private-question'},{('SAY','private-question')})
        self.assertEqual(rejection_event(caught.exception,'ACTION',1)['reason'],'REPEATED_ACTION')

    def test_record_shape_and_observation_id_rejections(self):
        bad=plan();bad['diagnosis_basis']=['reference-case-SECRET']
        shape=plan();shape['plans']=[]
        r=self.run_case(MockClient([{'action':'DONE'},bad,shape,plan()]))
        self.assertEqual([e['reason'] for e in r['rejection_events']],['UNKNOWN_OBSERVATION_ID','INVALID_PLAN_FIELDS'])
        self.assertTrue(all(e['phase']=='RECORD' for e in r['rejection_events']))
        self.assertNotIn('reference-case-SECRET',json.dumps(r))

    def test_action_sequence_records_choices_and_observed_success_without_text(self):
        r=self.run_case(MockClient([{'action':'SAY','content':'언제부터인가요?'},
            {'action':'EXAM','content':'복부 반발통 확인'},{'action':'DONE'},plan()]))
        events=r['action_sequence']
        self.assertEqual([e['action'] for e in events if e['event']=='MODEL_SELECTED'],['SAY','EXAM','DONE'])
        self.assertEqual([e['action'] for e in events if e['event']=='OBSERVATION_RECEIVED'],['SAY','EXAM'])
        self.assertEqual(events[-1]['action'],'DIAGNOSE')
        self.assertNotIn('복부 반발통',json.dumps(r,ensure_ascii=False))


class SharedLedgerTests(unittest.TestCase):
    def workspace(self):
        work=ROOT/'validation'
        work.mkdir(parents=True,exist_ok=True)
        return tempfile.TemporaryDirectory(dir=work)

    def setup_ledger(self,root):
        from sample_ledger_fixture import setup_ledger
        return setup_ledger(root)

    def test_same_ledger_only_one_extra_then_rerun_blocked(self):
        with self.workspace() as name,patch.object(runner,'ROOT',Path(name)):
            p=self.setup_ledger(Path(name));runner.reserve_session(p,'new',expected_attempts=2)
            self.assertEqual(len(runner.read_ledger(p)['attempts']),3)
            with self.assertRaises(NovaError):runner.reserve_session(p,'fourth',expected_attempts=2)
            self.assertEqual(len(runner.read_ledger(p)['attempts']),3)

    def test_copied_ledger_is_rejected(self):
        with self.workspace() as name,patch.object(runner,'ROOT',Path(name)):
            p=self.setup_ledger(Path(name));other=Path(name)/'clone.json';other.write_bytes(p.read_bytes())
            with self.assertRaises(NovaError) as caught:runner.check_shared_ledger(other)
            self.assertEqual(caught.exception.code,'LOCAL_WRONG_SHARED_LEDGER')

    def test_missing_ledger_not_initialized(self):
        with self.workspace() as name,patch.object(runner,'ROOT',Path(name)):
            p=self.setup_ledger(Path(name));p.unlink()
            with self.assertRaises(FileNotFoundError):runner.check_shared_ledger(p)
            self.assertFalse(p.exists())

    def test_existing_attempt_cannot_be_replaced(self):
        with self.workspace() as name,patch.object(runner,'ROOT',Path(name)):
            p=self.setup_ledger(Path(name));data=runner.read_ledger(p);data['attempts'][0]['request_id']='different'
            p.write_text(json.dumps(data))
            with self.assertRaises(NovaError) as caught:runner.check_shared_ledger(p)
            self.assertEqual(caught.exception.code,'LOCAL_SESSION_LEDGER_HISTORY_CHANGED')
