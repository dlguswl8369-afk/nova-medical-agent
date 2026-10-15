"""Publish validated numeric self-review summaries, never raw patient/evaluator text."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from evaluation_summary import DOMAINS
from run_public_comparison import CASES,save


def collect(root):
    root=Path(root);ledger=root/'self_review_ledger.json'
    entries=json.loads(ledger.read_text(encoding='utf-8'))['entries'] if ledger.exists() else {}
    rows=[]
    for case in CASES:
        row={'case':case,'status':entries.get(case,{}).get('status','NOT_EXECUTED'),
             'model':entries.get(case,{}).get('model'),'usage':entries.get(case,{}).get('usage'),
             'domains':{k:{'maximum':v,'baseline_score':None,'extended_score':None} for k,v in DOMAINS.items()},
             'baseline_total':None,'extended_total':None,'valid_score_schema':False}
        file=root/f'{case}_self_review_private.json'
        if file.exists():
            try:
                raw=json.loads(file.read_text(encoding='utf-8'))
                content=raw['choices'][0]['message']['content'].strip()
                if content.startswith('```'):content=content.split('\n',1)[1].rsplit('```',1)[0].strip()
                review=json.loads(content)
                domains=review['domains']
                if set(domains)!=set(DOMAINS):raise ValueError('DOMAIN_SET')
                for domain,maximum in DOMAINS.items():
                    for version in ('baseline','extended'):
                        value=domains[domain][version+'_score']
                        if value is not None and (type(value) not in (int,float) or not 0<=value<=maximum):
                            raise ValueError('SCORE_RANGE')
                        row['domains'][domain][version+'_score']=value
                row['valid_score_schema']=True
                for version in ('baseline','extended'):
                    values=[v[version+'_score'] for v in row['domains'].values()]
                    row[version+'_total']=sum(values) if all(v is not None for v in values) else None
            except (KeyError,IndexError,TypeError,ValueError):
                row['schema_error']='UNUSABLE_SCORE_RESPONSE_NO_RETRY'
                for scores in row['domains'].values():scores.update(baseline_score=None,extended_score=None)
        rows.append(row)
    return {'official_score':False,'independent_clinical_validation':False,
            'scope':'Up to three single-model self-reference comparisons after consultation; last reference packet only',
            'requests_recorded':len(entries),'cases':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runs',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();save(a.output,collect(a.runs))
