"""New synthetic responses, NOT reconstructed live failures or clinical evidence."""
import json
import unittest
import unicodedata
from unittest.mock import patch
from nova_agent import loop
from nova_agent.action_repair import repair_request, MARKER, MAX_REPAIR_BYTES
from nova_agent.diagnostics import parse_action, parse_object, Rejection
from nova_agent.prompts import RECORD
from test_agent import MockClient, NoResults, plan

SCENARIOS = {}

def say(text, **extra):
    return {'action': 'SAY', 'content': text, **extra}

class CaptureClient(MockClient):
    def __init__(self, outputs, usage='normal', failures=None):
        super().__init__(outputs, failures, opening='SYNTHETIC_PRIVATE_OPENING')
        self.sent=[]; self.usage_mode=usage; self.admissions=[]; self.state=None
    def _request(self, method, path, body=None):
        if (body or {}).get('action') in ('SAY','EXAM'):
            self.sent.append((body['action'],body['content']))
        if path.endswith('completions') and self.state:
            b=self.state.report['budget_ledger']; p=b['last_proposal']
            self.admissions.append((b['committed_input']+p['final_headroom_input'],
                b['committed_output']+p['final_headroom_output'],b['http_attempts']+p['final_headroom_calls']))
        result=super()._request(method,path,body)
        if path.endswith('completions'):
            if self.usage_mode=='missing': result.pop('usage',None)
            elif self.usage_mode=='partial': result['usage']={'prompt_tokens':300}
        return result

class RepairTests(unittest.TestCase):
    def run_case(self, outputs, usage='normal', failures=None, **config):
        c=CaptureClient(outputs,usage,failures)
        s=loop.State(NoResults(),loop.Config(retry_delay=0,**config));c.state=s
        loop.consult(c,s)
        for i,o,n in c.admissions:
            self.assertLessEqual(i,s.config.max_input_budget)
            self.assertLessEqual(o,s.config.max_output_budget)
            self.assertLessEqual(n,s.config.max_doctor_requests)
        self.assertTrue(all(e['actual_input_estimate']<=e['enforced_input_cap'] for e in s.report['record_envelope_checks']))
        return c,s.report

    def repair(self,obj):
        try: parse_action(obj,set())
        except ValueError as e: return repair_request(e,obj)
        self.fail('Expected rejection')

    def test_30_allowed_31_rejected(self):
        self.assertEqual(parse_action(say('가'*30),set())[1],'가'*30)
        with self.assertRaisesRegex(Rejection,'CONTENT_OVER_30'):parse_action(say('가'*31),set())

    def test_nfc_boundary_and_exact_transmitted_string(self):
        decomposed=unicodedata.normalize('NFD','가'*30)
        c,r=self.run_case([say(' '+decomposed+' '),{'action':'DONE'},plan()])
        self.assertEqual(c.sent,[('SAY','가'*30)])
        with self.assertRaises(Rejection) as e:parse_action(say(unicodedata.normalize('NFD','가'*31)),set())
        self.assertEqual(e.exception.chars,31)

    def test_33_32_25_recovers_without_truncation(self):
        c,r=self.run_case([say('가'*33),say('나'*32),say('다'*25),{'action':'DONE'},plan()])
        self.assertEqual(c.sent,[('SAY','다'*25)])
        self.assertEqual(r['termination_reason'],'DOCTOR_DONE')
        self.assertTrue(r['successful_execution'])
        self.assertEqual([e['content_chars'] for e in r['rejection_events']],[33,32])
        second=json.loads(c.prompts[1][1]['content'].split(MARKER)[1])
        third=json.loads(c.prompts[2][1]['content'].split(MARKER)[1])
        self.assertEqual(second['actual_nfc_chars'],33);self.assertEqual(third['actual_nfc_chars'],32)
        self.assertEqual(third['previous_candidate_not_observation']['content'],'나'*32)
        self.assertNotIn('가'*33,c.prompts[2][1]['content'])
        SCENARIOS['33_32_25']={'synthetic_only':True,'rejected_lengths':[33,32],
            'sent_lengths':[len(t) for _,t in c.sent],'termination':r['termination_reason'],
            'mock_usage_input':r['reported_prompt_tokens'],'repairs':r['action_repairs']}

    def test_persistent_overlength_stops_and_attempts_final(self):
        c,r=self.run_case([say('가'*33),say('나'*32),say('다'*32),plan()])
        self.assertEqual(c.sent,[]);self.assertEqual(r['doctor_http_attempts'],4)
        self.assertEqual(r['termination_reason'],'LOCAL_ACTION_FORMAT_RETRIES_EXHAUSTED')
        self.assertFalse(r['successful_execution']);self.assertTrue(r['submitted'])
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        self.assertEqual(r['final_http_attempts'],1)

    def test_reason_specific_instructions(self):
        codes=['CONTENT_OVER_30','ACTION_NOT_ALLOWED','REPEATED_ACTION','JSON_PARSE_FAILED',
            'OBJECT_REQUIRED','CONTENT_TYPE','EMPTY_CONTENT','INVALID_INTENT','RESPONSE_TOO_LONG']
        instructions=[]
        for code in codes:
            text,a=repair_request(Rejection(code,33),say('합성 후보'))
            instructions.append(json.loads(text.split(MARKER)[1])['instruction'])
            self.assertEqual(a['reason'],code)
        self.assertEqual(len(set(instructions)),len(codes))

    def test_forbidden_regeneration_never_converted_to_exam(self):
        c,r=self.run_case([say('가'*33),{'action':'TEST','content':'합성 검사'}, {'action':'DONE'},plan()])
        self.assertEqual(c.sent,[])
        self.assertEqual([e['reason'] for e in r['rejection_events']],['CONTENT_OVER_30','ACTION_NOT_ALLOWED'])
        self.assertIn('SAY, EXAM, DONE',c.prompts[2][1]['content'])

    def test_repeat_after_repair_is_revalidated(self):
        c,r=self.run_case([say('합성 질문'),say('가'*33),say('합성 질문'),{'action':'DONE'},plan()])
        self.assertEqual(c.sent,[('SAY','합성 질문')])
        self.assertEqual([e['reason'] for e in r['rejection_events']],['CONTENT_OVER_30','REPEATED_ACTION'])
        self.assertIn('이미 성공적으로 수행',c.prompts[3][1]['content'])

    def test_nfc_repeat_rejected(self):
        with self.assertRaisesRegex(Rejection,'REPEATED_ACTION'):
            parse_action(say(unicodedata.normalize('NFD','가')), {('SAY','가')})

    def test_failed_server_action_not_marked_performed(self):
        c,r=self.run_case([{'action':'EXAM','content':'합성 복부 진찰'}]*2+[{'action':'DONE'},plan()],
            failures={'EXAM':['EXAM_NOT_SPECIFIC',None]})
        self.assertEqual(r['actions_succeeded'],1)
        self.assertFalse(any(e['reason']=='REPEATED_ACTION' for e in r['rejection_events']))
        self.assertEqual(r['observed_fact_count'],3)

    def test_semantic_example_is_synthetic_and_instructed_not_proven(self):
        original='어제부터 걷지 않을 때에도 왼쪽 무릎 안쪽에 통증이 느껴지나요?'
        rewritten='어제부터 안 걸어도 왼쪽 무릎 안쪽 통증은?'
        self.assertGreater(len(original),30);self.assertLessEqual(len(rewritten),30)
        for token in ('어제부터','안 걸어도','왼쪽','무릎 안쪽'):self.assertIn(token,rewritten)
        c,r=self.run_case([say(original),say(rewritten),{'action':'DONE'},plan()])
        self.assertEqual(c.sent,[('SAY',rewritten)])
        instruction=c.prompts[1][1]['content']
        for word in ('부정','좌우','부위','시간','조건','같은 의도'):
            self.assertIn(word,instruction)
        self.assertIn(original,instruction)

    def test_json_raw_not_reinserted_or_executed(self):
        raw="__import__('os').system('SYNTHETIC_PRIVATE_COMMAND')"
        c,r=self.run_case([raw,{'action':'DONE'},plan()])
        self.assertNotIn(raw,c.prompts[1][1]['content'])
        self.assertEqual(r['rejection_events'][0]['reason'],'JSON_PARSE_FAILED')

    def test_unparsed_response_does_not_reuse_stale_candidate(self):
        c,r=self.run_case([say('가'*33),'bad JSON',{'action':'DONE'},plan()])
        self.assertNotIn('가'*33,c.prompts[2][1]['content'])
        self.assertIsNone(json.loads(c.prompts[2][1]['content'].split(MARKER)[1])['previous_candidate_not_observation'])

    def test_large_candidate_omitted_not_sliced(self):
        suffix,a=self.repair(say('비'*257))
        self.assertFalse(a['candidate_included']);self.assertNotIn('비'*30,suffix)
        self.assertLessEqual(a['repair_bytes'],MAX_REPAIR_BYTES)

    def test_huge_unparsed_response_not_reinserted(self):
        c,r=self.run_case(['SYNTHETIC_PRIVATE_RAW'*2000,{'action':'DONE'},plan()])
        self.assertEqual(r['rejection_events'][0]['reason'],'RESPONSE_TOO_LONG')
        self.assertNotIn('SYNTHETIC_PRIVATE_RAW',c.prompts[1][1]['content'])

    def test_only_candidate_fields_in_memory_and_no_raw_in_report(self):
        bad=say('SYNTHETIC_PRIVATE_CANDIDATE'+'x'*10,extra='SYNTHETIC_PRIVATE_FIELD')
        c,r=self.run_case([bad,{'action':'DONE'},plan()])
        self.assertNotIn('SYNTHETIC_PRIVATE_FIELD',c.prompts[1][1]['content'])
        report=json.dumps(r,ensure_ascii=False)
        for marker in ('SYNTHETIC_PRIVATE_CANDIDATE','SYNTHETIC_PRIVATE_FIELD','SYNTHETIC_PRIVATE_OPENING'):
            self.assertNotIn(marker,report)

    def test_repairs_do_not_enter_observations_or_final_context(self):
        c,r=self.run_case([say('SYNTHETIC_PRIVATE_CANDIDATE'+'x'*10),{'action':'DONE'},plan()])
        final=c.prompts[-1]
        self.assertEqual(final[0]['content'],RECORD)
        self.assertNotIn(MARKER,final[1]['content'])
        self.assertNotIn('SYNTHETIC_PRIVATE_CANDIDATE',final[1]['content'])
        self.assertEqual(len(json.loads(final[1]['content'])['current_patient_observations']),2)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANDIDATE',json.dumps(c.submissions))
        self.assertEqual(c.submissions[0]['note']['O']['tests'],'')

    def test_final_retries_still_have_only_record_suffix(self):
        c,r=self.run_case([say('가'*33),{'action':'DONE'},'bad','bad',plan()])
        self.assertEqual(r['final_http_attempts'],3)
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        for p in c.prompts[-3:]:self.assertNotIn(MARKER,p[1]['content'])

    def test_repair_usage_is_settled(self):
        c,r=self.run_case([say('가'*33),say('나'*32),{'action':'DONE'},plan()])
        self.assertEqual(r['budget_ledger']['confirmed_input'],1200)
        self.assertEqual(r['budget_ledger']['confirmed_output'],400)
        self.assertEqual(r['budget_ledger']['uncertain_reserved_input'],0)
        self.assertEqual(r['budget_ledger']['unique_requests'],4)

    def test_repair_missing_and_partial_usage_remain_reserved(self):
        for usage in ('missing','partial'):
            c,r=self.run_case([say('가'*33),{'action':'DONE'},plan()],usage=usage)
            self.assertGreater(r['budget_ledger']['uncertain_reserved_input'],0)
            self.assertEqual(r['budget_ledger']['confirmed_input'],0)
            self.assertEqual(r['budget_ledger']['uncertain_reserved_output'],8192)

    def test_uncertain_repair_transport_uses_same_id_reservation(self):
        c,r=self.run_case([say('가'*33),{'action':'DONE'},plan()],usage='missing',
            failures={'CHAT':[None,'API_UNAVAILABLE',None]})
        self.assertEqual(r['doctor_http_attempts'],4)
        self.assertEqual(r['budget_ledger']['unique_requests'],3)
        self.assertEqual(r['model_retries'],1)
        self.assertGreater(r['budget_ledger']['uncertain_reserved_input'],0)

    def test_call_budget_blocks_repair_preserving_final(self):
        c,r=self.run_case([say('가'*33),plan()],max_doctor_requests=4)
        self.assertEqual(r['termination_reason'],'LOCAL_MODEL_BUDGET')
        self.assertEqual(r['doctor_http_attempts'],2)
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')

    def test_output_budget_blocks_repair_preserving_final(self):
        c,r=self.run_case([say('가'*33),plan()],max_output_budget=14336,usage='missing')
        self.assertEqual(r['termination_reason'],'LOCAL_MODEL_BUDGET')
        self.assertEqual(r['final_http_attempts'],1)
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')

    def test_input_boundary_counts_repair_suffix_and_preserves_final(self):
        from nova_agent.record_budget import input_charge, RecordEnvelope
        from nova_agent.prompts import STEP
        probe=CaptureClient([])
        s=loop.State(NoResults(),loop.Config(retry_delay=0))
        run=loop.Run(probe,s,probe.session())
        from nova_agent.context import fact, observation_text
        run.facts=[fact('F0','opening',probe.initial['opening']),
            fact('F1','vitals',observation_text(probe.initial['vital_signs']))]
        base,_=run.context(30)
        first=input_charge(STEP,base)
        # Stopping adds the existing fixed error code to the final clinical packet.
        # Fund that explicit growth too; the recovery candidate still cannot enter it.
        final_context=json.loads(base)
        final_context['recent_action_error_codes_not_patient_facts']=['LOCAL_MODEL_BUDGET']
        final_base=json.dumps(final_context,ensure_ascii=False)
        cap=first+RecordEnvelope(final_base,3).headroom()[0]
        c,r=self.run_case([say('가'*33),plan()],max_input_budget=cap,usage='missing')
        self.assertEqual(r['termination_reason'],'LOCAL_MODEL_BUDGET')
        self.assertEqual(r['final_http_attempts'],1)
        self.assertEqual(r['record_outcome'],'DOCTOR_RECORD_VALIDATED')
        blocked=[e for e in r['budget_ledger']['events'] if e['event']=='BLOCKED'][0]
        self.assertGreater(blocked['next_input_reservation'],first)

    def test_audit_reads_base_only_and_exports_no_candidate(self):
        from sample_audit import SampleAudit
        c,r=self.run_case([say('SYNTHETIC_PRIVATE_CANDIDATE'+'x'*10),{'action':'DONE'},plan()])
        audit=SampleAudit();audit.initial=c.initial
        for messages in c.prompts:
            row=audit.chat_request({'messages':messages,'max_tokens':2048})
            self.assertTrue(row['context_present'])
            self.assertTrue(row['observations_match_sdk_responses'])
            self.assertEqual(row['fact_ids'],['F0','F1'])
        self.assertNotIn('SYNTHETIC_PRIVATE_CANDIDATE',json.dumps(audit.report()))

    def test_repair_new_id_keeps_uncertain_previous_request(self):
        c,r=self.run_case([say('가'*33),{'action':'DONE'},plan()],
            failures={'CHAT':[None,'PROVIDER_RESPONSE_INVALID',None]})
        self.assertEqual(r['doctor_http_attempts'],4)
        self.assertEqual(r['budget_ledger']['unique_requests'],4)
        self.assertGreater(r['budget_ledger']['uncertain_reserved_input'],0)
        self.assertEqual(r['budget_ledger']['confirmed_input'],900)

    def test_repair_deadline_blocks_more_calls(self):
        c=CaptureClient([say('가'*33)])
        s=loop.State(NoResults(),loop.Config(retry_delay=0))
        # First loop boundary and first request allowed; subsequent repair has no model time.
        with patch.object(loop.Run,'left',side_effect=[1000,1000,1000,9,9,5,5]):
            loop.consult(c,s)
        self.assertEqual(s.report['doctor_http_attempts'],1)
        self.assertEqual(s.report['termination_reason'],'LOCAL_DEADLINE')
        self.assertEqual(s.report['record_outcome'],'LOCAL_OBSERVATION_ONLY_FALLBACK')

    def test_repair_size_bound_and_non_accumulation(self):
        c,r=self.run_case([say('😀'*256),say('나'*32),{'action':'DONE'},plan()])
        for p in c.prompts[:3]:self.assertLessEqual(p[1]['content'].count(MARKER),1)
        self.assertTrue(all(a['repair_bytes']<=MAX_REPAIR_BYTES for a in r['action_repairs']))
        self.assertNotIn('😀',c.prompts[2][1]['content'])

    def test_intent_and_field_revalidation(self):
        c,r=self.run_case([say('합성 질문',intent='INVALID'),say([]),{'action':'DONE'},plan()])
        self.assertEqual([e['reason'] for e in r['rejection_events']],['INVALID_INTENT','CONTENT_TYPE'])
        self.assertEqual(c.sent,[])

if __name__=='__main__':unittest.main()
