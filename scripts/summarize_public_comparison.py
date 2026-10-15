"""Export only aggregate metrics; never copy keys, session IDs, or patient text."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from evaluation_summary import summarize
from run_public_comparison import CASES, PURPOSE, save


def collect(root):
    root=Path(root);rows=[];started=completed=0
    for case in CASES:
        pair={}
        for version in ('v3.2','v3.3'):
            path=root/f'{case}_{version}.json'
            data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            private=root/f'{case}_{version}_private.json'
            raw=json.loads(private.read_text(encoding='utf-8')) if private.exists() else {}
            status=data.get('status','NOT_EXECUTED')
            started+=bool(data.get('session_id'))
            completed+=status=='completed'
            row={'case':case,'version':version,'status':status,
                 'prepare_seconds':data.get('prepare_seconds'),'elapsed_seconds':data.get('elapsed_seconds'),
                 'app_sha256':data.get('app_sha256'),'error_code':data.get('error'),
                 'evaluation':summarize(raw.get('events',[]),raw.get('final'),raw.get('report'))}
            report=data.get('report',{})
            row['execution_outcome']={k:report.get(k) for k in ('termination_reason','termination_kind',
                'record_outcome','degraded','record_fields_valid','diagnosis_unresolved','action_counts',
                'invalid_model_outputs','usage_missing_responses')}
            pair[version]=row;rows.append(row)
        # Null means not measurable; never convert missing usage to zero.
        left,right=pair['v3.2'],pair['v3.3']
        delta={}
        for field in ('doctor_http_attempts','doctor_successes','reported_prompt_tokens',
                      'reported_completion_tokens','duration_seconds'):
            a=left['evaluation']['usage'][field];b=right['evaluation']['usage'][field]
            delta[field]=b-a if isinstance(a,(int,float)) and isinstance(b,(int,float)) else None
        right['difference_from_baseline']=delta
    return {'purpose':PURPOSE,'maximum_new_sessions':6,'sessions_with_ids':started,'completed':completed,
            'official_score':False,'clinical_quality_evaluated':False,'actual_api_cost_usd':None,
            'cost_note':'No invented dollar conversion; use team billing and recorded usage.',
            'cases':rows,'self_review_calls':0 if not (root/'self_review_ledger.json').exists() else
            len(json.loads((root/'self_review_ledger.json').read_text(encoding='utf-8'))['entries'])}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runs',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();save(a.output,collect(a.runs))
