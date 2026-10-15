import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmark_adapters import select_cases, ask_ddx


def main():
    p=argparse.ArgumentParser();p.add_argument('--zip',required=True);p.add_argument('--report',required=True)
    a=p.parse_args();start=time.monotonic()
    source=Path(a.zip)
    if hashlib.sha256(source.read_bytes()).hexdigest()!='a2b4dbc6a2bc177a54cf7c7f1a4e15f94625bfd335738737b575c6832a1060a7':
        raise ValueError('BENCHMARK_HASH_MISMATCH')
    cases,dictionary,counts=select_cases(source)
    checks=[]
    for case in cases:
        view=case.doctor_input()
        assert set(view)=={'case_id','task','observations','language','translation'}
        assert not any(k in view['observations'] for k in ['diagnosis','Correct_Diagnosis','note','reference_note','Test_Results','EVIDENCES','PATHOLOGY'])
        check={'case_id':case.case_id,'dataset':case.dataset,'split':case.split,'parse':'PASS',
               'doctor_allowlist':'PASS','evaluator_target_present':bool(case.evaluator_private),
               'translated':False,'model_run':False,'clinical_score':None}
        if case.dataset=='DDXPlus':
            answer=ask_ddx(case,case.initial['initial_evidence_code'],dictionary)
            assert answer['answer']==case.initial['initial_response']
            check['question_mapping']='PASS'
        if case.dataset=='ACI-Bench':assert case.evaluator_private['diagnosis_accuracy'] is None
        checks.append(check)
    assert len(checks)==15
    result={'seed':20261015,'counts':counts,'sampled':checks,'total':len(checks),
            'seconds':time.monotonic()-start,'real_api_calls':0,'scope':'Parsing, projection and mapping only; no clinical performance evaluation'}
    dest=Path(a.report);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checked':len(checks),'seconds':result['seconds']}))

if __name__=='__main__':main()
