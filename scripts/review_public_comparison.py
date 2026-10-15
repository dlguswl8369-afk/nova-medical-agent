"""Optional off-session self-review, at most three fixed requests. Not official scores."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'app')]
from evaluation_summary import comparison_review_payload, DOMAINS, summarize
from run_public_comparison import save, CASES, ROOT
from nova_sdk import Client


def run_reviews(runs,samples,key):
    root=Path(runs).resolve()
    if root.is_relative_to(ROOT):raise ValueError('PRIVATE_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY')
    comparisons={}
    for case in CASES:
        rows=[]
        for version in ('v3.2','v3.3'):
            status=json.loads((root/f'{case}_{version}.json').read_text(encoding='utf-8'))
            if status.get('status')!='completed':raise ValueError('ALL_SIX_RUNS_MUST_COMPLETE')
            raw=json.loads((root/f'{case}_{version}_private.json').read_text(encoding='utf-8'))
            rows.append({'events':raw['events'],'final':raw['final'],
                         'last_reference_context':raw['last_reference_context'],
                         'aggregate':summarize(raw['events'],raw['final'],raw['report']),
                         'termination_reason':raw['report'].get('termination_reason')})
        payload=comparison_review_payload(*rows)
        payload['public_case_for_evaluator_only']=json.loads((Path(samples)/case/'case.json').read_text(encoding='utf-8'))
        payload['output_contract']={'domains':{k:{'baseline_score':'0..maximum or null when evidence insufficient',
                                    'extended_score':'0..maximum or null when evidence insufficient',
                                    'maximum':v,'evidence':'cite actual turns and record fields'} for k,v in DOMAINS.items()},
                                    'relevance':'last reference packet only; do not generalize to all packets',
                                    'label':'Non-official self-reference evaluation'}
        comparisons[case]=json.dumps(payload,ensure_ascii=False)
        if len(comparisons[case])>300000:raise ValueError('REVIEW_INPUT_TOO_LARGE_NO_CALL')
    client=Client(api_base='https://nova.snubhai.org',token=key,sample=True)
    client.session_id=''  # Never inherit a NOVA_SESSION_ID from a development shell.
    ledger=root/'self_review_ledger.json';lock=root/'self_review.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        data=json.loads(ledger.read_text()) if ledger.exists() else {'maximum_requests':3,'entries':{}}
        for case in CASES:
            if case in data['entries']:
                if data['entries'][case]['status']=='COMPLETED':continue
                raise RuntimeError('PENDING_REVIEW_REQUIRES_STATUS_RECONCILIATION')
            if len(data['entries'])>=3:raise ValueError('SELF_REVIEW_LIMIT')
            row={'request_id':str(uuid.uuid4()),'status':'PENDING','model':'openai/gpt-6.1-sol',
                 'input_sha256':hashlib.sha256(comparisons[case].encode()).hexdigest()}
            data['entries'][case]=row;save(ledger,data)
            try:
                response=client.chat([{'role':'system','content':'Return a JSON evidence-based comparison. This is NOT an official NOVA score. Do not infer performed actions from final notes.'},
                                      {'role':'user','content':comparisons[case]}],model=row['model'],
                                     reasoning_effort='medium',max_tokens=4000,request_id=row['request_id'])
                save(root/f'{case}_self_review_private.json',response)
                row.update(status='COMPLETED',usage=response.get('usage'),official_score=False)
                save(ledger,data)
            except Exception:
                row['status']='UNCERTAIN_OR_FAILED_NO_REPLACEMENT';save(ledger,data)
                raise
    finally:lock.unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--runs',required=True);p.add_argument('--samples',required=True)
    a=p.parse_args()
    key=os.environ.get('NOVA_DEV_KEY')
    if not key:
        if not sys.stdin.isatty():raise RuntimeError('USE_PRIVATE_TERMINAL')
        key=getpass.getpass('NOVA key for up to 3 off-session reviews (hidden): ')
    run_reviews(a.runs,a.samples,key)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('STOP:',getattr(exc,'code',type(exc).__name__))
        raise SystemExit(1)
