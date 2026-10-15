"""Long synthetic consultations and exact final-input envelope regressions."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'tests')]
from nova_agent import loop
from nova_agent.budget import Budget
from nova_agent.prompts import RECORD
from nova_agent.record_budget import RecordEnvelope, RECORD_REPAIR, input_charge, fit_record_envelope
from nova_sdk import NovaError
from test_agent import MockClient, NoResults, plan

SCENARIOS={}

def packet(refs=None):
    return json.dumps({'current_patient_observations':[{'id':'F0','kind':'opening','text':'synthetic observation'}],
        'observations_omitted':0,'reference_evidence':refs or [],'turns_left':10},ensure_ascii=False)


class EnvelopeTests(unittest.TestCase):
    def test_each_retry_charge_uses_actual_serialization(self):
        base=packet([{'text':'quote " newline\n 역슬래시 \\ 한글 😀','unit_id':'U'}])
        e=RecordEnvelope(base,3)
        expected=[input_charge(RECORD,base+RECORD_REPAIR*i) for i in range(3)]
        self.assertEqual(list(e.charges),expected)
        self.assertEqual(e.headroom(),(sum(expected),12288,3))
        self.assertEqual(e.audit()['retry_clinical_context_growth_bytes'],0)
        self.assertLess(sum(expected),300000)

    def test_reported_170k_plus_40k_boundary_is_admitted(self):
        base=packet([{'unit_id':'U','text':'x'*34000}]);e=RecordEnvelope(base,3)
        b=Budget(500000,100000,80)
        b.reserve('history',170000,1000,'history');b.settle('history',{'prompt_tokens':170000,'completion_tokens':1000})
        with self.assertRaises(NovaError):b.reserve('old-action',40000,2048,'next',headroom=(300000,12288,3))
        b.reserve('new-action',40000,2048,'next',headroom=e.headroom())
        self.assertLessEqual(170000+40000+sum(e.charges),500000)
        SCENARIOS['170000_plus_40000']={'old_required_input':510000,'new_required_input':210000+sum(e.charges),
            'record_envelope':e.audit(),'new_allowed':True}

    def test_mutated_clinical_context_rejected_even_if_shorter(self):
        e=RecordEnvelope(packet(),3)
        for user in (packet().replace('synthetic observation','x'),e.base_user+'new clinical data',e.base_user+RECORD_REPAIR*3):
            with self.assertRaises(NovaError) as c:e.validate(RECORD,user,2)
            self.assertEqual(c.exception.code,'LOCAL_RECORD_ENVELOPE_MISMATCH')

    def test_repair_count_cannot_outrun_transmission_ordinal(self):
        e=RecordEnvelope(packet(),3)
        with self.assertRaises(NovaError):e.validate(RECORD,e.base_user+RECORD_REPAIR,0)
        for ordinal in range(3):
            e.validate(RECORD,e.base_user,ordinal) # same-ID transport retries
            e.validate(RECORD,e.base_user+RECORD_REPAIR*ordinal,ordinal)

    def test_new_context_fits_by_removing_whole_lowest_ranked_reference(self):
        refs=[{'unit_id':'higher','text':'A'*1000},{'unit_id':'lower','text':'B'*5000}]
        original=packet(refs);small=packet(refs[:1]);cap=sum(RecordEnvelope(small,3).charges)
        e,a=fit_record_envelope(original,3,(cap,12288,3),mode='TEST')
        value=json.loads(e.base_user)
        self.assertEqual(value['reference_evidence'],refs[:1])
        self.assertEqual(value['current_patient_observations'],json.loads(original)['current_patient_observations'])
        self.assertEqual(a['observations_removed'],0)
        self.assertEqual(a['removed_reference_units'],[{'unit_id':'lower','reason':'FINAL_RECORD_ENVELOPE_BUDGET'}])
        self.assertEqual(sum(e.charges),cap)

    def test_unfundable_observations_fail_closed_without_slicing(self):
        original=packet()
        with self.assertRaises(NovaError) as c:fit_record_envelope(original,3,(10,12288,3),mode='TEST')
        self.assertEqual(c.exception.code,'LOCAL_FINAL_CONTEXT_BUDGET')
        self.assertEqual(original,packet())

    def test_single_prompt_limit_applies_to_all_repair_generations(self):
        original=packet([{'unit_id':'large','text':'x'*99000}])
        e,a=fit_record_envelope(original,3,(500000,12288,3),mode='TEST')
        self.assertEqual(a['reference_units_after'],0)
        self.assertTrue(all(c<=100000 for c in e.charges))

    def test_insufficient_output_or_calls_does_not_discard_context_to_hide_it(self):
        for available in ((500000,12287,3),(500000,12288,2)):
            with self.assertRaises(NovaError):fit_record_envelope(packet([{'unit_id':'U','text':'abc'}]),3,available,mode='TEST')


class LongClient(MockClient):
    def __init__(self,usage_mode='normal',record_mode='normal',growing=False):
        super().__init__(opening='합성 통증 '*2000)
        self.usage_mode,self.record_mode,self.growing=usage_mode,record_mode,growing
        self.action_models,self.final_models=0,0
        self.outputs=[self.choose]*100
        self.state=None
        self.admissions=[]
    def choose(self,body):
        if body['max_tokens']==4096:
            self.final_models+=1
            return 'bad synthetic JSON' if self.record_mode=='repair' and self.final_models<3 else plan()
        self.action_models+=1
        return {'action':'SAY','content':f'합성 질문 {self.action_models}?'} if self.action_models<=25 else {'action':'DONE'}
    def _request(self,method,path,body=None):
        if path.endswith('completions') and self.state and 'budget_ledger' in self.state.report:
            b=self.state.report['budget_ledger'];p=b['last_proposal']
            self.admissions.append({'phase':p['phase'],'committed_input':b['committed_input'],
                'future_input':p['final_headroom_input'],'committed_output':b['committed_output'],
                'future_output':p['final_headroom_output'],'calls':b['http_attempts'],'future_calls':p['final_headroom_calls']})
        result=super()._request(method,path,body)
        if path.endswith('completions'):
            if self.usage_mode=='missing':result.pop('usage')
            elif self.usage_mode=='partial':result['usage']={'prompt_tokens':8500}
            else:result['usage']={'prompt_tokens':8500,'completion_tokens':100,'total_tokens':8600}
        if self.growing and (body or {}).get('action')=='SAY':
            result['content']='관찰된 합성 답변 '*30
        return result


class ConsultationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('nova_agent._v3_baseline',ROOT/'tests/fixtures/v3_loop_before.py')
        cls.old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=cls.old;spec.loader.exec_module(cls.old)

    def run_case(self,version,usage='normal',record='normal',growing=False):
        c=LongClient(usage,record,growing)
        s=version.State(NoResults(),version.Config(retry_delay=0))
        c.state=s;version.consult(c,s)
        return c,s.report

    def check_limits(self,client,report):
        for a in client.admissions:
            self.assertLessEqual(a['committed_input']+a['future_input'],500000)
            self.assertLessEqual(a['committed_output']+a['future_output'],100000)
            self.assertLessEqual(a['calls']+a['future_calls'],80)
        self.assertLessEqual(report['budget_ledger']['committed_input'],500000)
        self.assertTrue(all(x['actual_input_estimate']<=x['enforced_input_cap'] for x in report['record_envelope_checks']))

    def record_scenario(self,name,client,report):
        SCENARIOS[name]={'action_counts':report['action_counts'],'doctor_calls':report['doctor_http_attempts'],
            'termination_reason':report['termination_reason'],'record_outcome':report['record_outcome'],
            'budget':report['budget_ledger'],'admissions':client.admissions,
            'record_envelope_checks':report.get('record_envelope_checks',[]),
            'record_context_packing':report.get('record_context_packing',[]),
            'action_record_headrooms':report.get('action_record_headrooms',[]),'submitted':report['submitted']}

    def test_multiple_turns_normal_usage_improves_over_fixed_300000(self):
        oldc,old=self.run_case(self.old);newc,new=self.run_case(loop)
        self.assertEqual(old['termination_reason'],'LOCAL_MODEL_BUDGET')
        self.assertEqual(new['termination_reason'],'DOCTOR_DONE')
        self.assertGreater(new['action_counts']['SAY'],old['action_counts']['SAY'])
        self.assertEqual(new['action_counts']['SAY'],25)
        self.assertEqual(new['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        self.assertEqual(new['budget_ledger']['uncertain_reserved_input'],0)
        self.check_limits(newc,new)
        self.record_scenario('normal_v3_fixed',oldc,old);self.record_scenario('normal_v3_1',newc,new)

    def test_growing_observations_update_exact_current_context(self):
        c,r=self.run_case(loop,growing=True)
        self.check_limits(c,r)
        self.assertEqual(r['termination_reason'],'DOCTOR_DONE')
        caps=[e['base_input_estimate'] for e in r['action_record_headrooms']]
        self.assertGreater(caps[-1],caps[0])
        self.assertEqual(r['record_context_packing'][0]['observations_removed'],0)
        self.record_scenario('growing_observations',c,r)

    def test_uncertain_requests_accumulate_and_leave_three_final_generations(self):
        for usage in ('missing','partial'):
            with self.subTest(usage=usage):
                c,r=self.run_case(loop,usage=usage,record='repair')
                self.check_limits(c,r)
                self.assertEqual(r['termination_reason'],'LOCAL_MODEL_BUDGET')
                self.assertEqual(r['final_http_attempts'],3)
                self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
                self.assertEqual(r['budget_ledger']['confirmed_input'],0)
                self.assertGreater(r['budget_ledger']['uncertain_reserved_input'],0)
                self.assertEqual(r['budget_ledger']['unique_requests'],r['doctor_http_attempts'])
                self.record_scenario('uncertain_'+usage,c,r)

    def test_missing_final_usage_and_same_id_retry_keep_remaining_headroom(self):
        c=LongClient('missing');s=loop.State(NoResults(),loop.Config(retry_delay=0));c.state=s
        original=c.chat;timed_out=False
        def chat(messages,**kwargs):
            nonlocal timed_out
            if kwargs['max_tokens']==4096 and not timed_out:
                timed_out=True;raise TimeoutError('SYNTHETIC')
            return original(messages,**kwargs)
        c.chat=chat;loop.consult(c,s);r=s.report
        self.check_limits(c,r)
        self.assertEqual(r['final_http_attempts'],2)
        self.assertEqual(r['model_retries'],1)
        self.assertEqual(r['budget_ledger']['http_attempts'],r['budget_ledger']['unique_requests']+1)
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        self.record_scenario('uncertain_same_id_final_retry',c,r)

    def test_actual_calls_reject_context_mutation_not_just_oversize(self):
        c=MockClient();s=loop.State(NoResults(),loop.Config(retry_delay=0));r=loop.Run(c,s,c.session())
        r.record_envelope=RecordEnvelope(packet(),3)
        with self.assertRaises(NovaError):r.doctor(RECORD,packet().replace('synthetic observation','different'),final=True)
        self.assertEqual(r.report['doctor_http_attempts'],0)

    def test_final_new_id_provider_regeneration_is_separately_reserved(self):
        c=LongClient('missing');s=loop.State(NoResults(),loop.Config(retry_delay=0));c.state=s
        original=c.chat;failed=False
        def chat(messages,**kwargs):
            nonlocal failed
            if kwargs['max_tokens']==4096 and not failed:
                failed=True;raise NovaError('PROVIDER_RESPONSE_INVALID')
            return original(messages,**kwargs)
        c.chat=chat;loop.consult(c,s);r=s.report
        self.check_limits(c,r)
        self.assertEqual(r['final_http_attempts'],2)
        self.assertEqual(r['budget_ledger']['http_attempts'],r['budget_ledger']['unique_requests'])
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        self.record_scenario('uncertain_new_id_final_retry',c,r)
