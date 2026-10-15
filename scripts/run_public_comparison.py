"""Six-session, fail-closed public comparison. Credentials stay in memory.

Run from a private terminal. Raw runs/ledger MUST be outside the Git checkout.
The old v3.2 ledger is neither read into nor copied into this new ledger.
"""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
CASES=('C01','C10','C03')
PURPOSE='v3.2 legacy 774 vs v3.3 legacy+organizer; same Config/model/effort, 3 paired public cases'


def save(path, value):
    path=Path(path);temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def app_hash(folder):
    rows=[]
    for p in sorted(Path(folder).rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            rows.append((p.relative_to(folder).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def worker(a):
    sys.path.insert(0,str(Path(a.app).resolve()))
    from nova_sdk import Client
    from nova_agent import prepare, consult
    key=sys.stdin.readline().rstrip('\r\n')
    if not key:raise RuntimeError('KEY_REQUIRED')
    entry=Path(a.entry);row=json.loads(entry.read_text(encoding='utf-8'))
    os.environ['NOVA_RAG_SOURCES']='legacy' if row['version']=='v3.2' else 'legacy,guidelines'
    events=[]; last_context={}; final={}

    class AuditClient(Client):
        def _request(self,method,path,body=None):
            if path=='/v1/chat/completions' and body:
                for message in body.get('messages',[]):
                    if message.get('role')=='user':
                        try:context=json.loads(message['content'])
                        except (ValueError,TypeError):continue
                        if isinstance(context,dict) and 'reference_evidence' in context:
                            last_context.clear();last_context.update(context)
            try:
                response=super()._request(method,path,body)
            except Exception as exc:
                if body and 'action' in body:
                    events.append({'action':body['action'],'content':body.get('content'),
                                   'error':getattr(exc,'code',type(exc).__name__)})
                raise
            if body and 'action' in body:
                events.append({'action':body['action'],'content':body.get('content'), 'response':response})
                if body['action']=='DIAGNOSE':final.update(note=body['note'],diagnosis=body['diagnosis'])
            return response

    client=AuditClient(api_base='https://nova.snubhai.org',token=key,sample=True)
    started=time.monotonic();state=None
    try:
        state=prepare()  # Never spend a session on an index/path preparation failure.
        row['prepare_seconds']=time.monotonic()-started
        row['status']='CREATE_PENDING';save(entry,row)
        session=client.create_sample(row['case_uuid'],request_id=row['create_request_id'])
        row.update(session_id=session['session_id'],status='ACTIVE');save(entry,row)
        consult(client,state)
        actual=client.session()
        row.update(status=actual.get('status','UNKNOWN'),elapsed_seconds=time.monotonic()-started,
                   report=state.report,final_record_present=bool(final))
        save(entry,row)
    except Exception as exc:
        row.update(status='REQUIRES_RECONCILIATION' if row.get('status')=='CREATE_PENDING' else 'FAILED_NEEDS_REVIEW',
                   error=getattr(exc,'code',type(exc).__name__),elapsed_seconds=time.monotonic()-started)
        save(entry,row)
    finally:
        save(entry.with_name(entry.stem+'_private.json'),{'events':events,'final':final,
             'last_reference_context':last_context,'report':state.report if state else {}})
    return 0 if row.get('status')=='completed' and final else 1


def main(a):
    out=Path(a.output).resolve()
    if out.is_relative_to(ROOT):raise ValueError('PRIVATE_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY')
    out.mkdir(parents=True,exist_ok=True)
    lock=out/'comparison.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        sys.path.insert(0,str(ROOT/'app'))
        from nova_sdk import Client
        key=sys.stdin.readline().rstrip('\r\n') if getattr(a,'key_stdin',False) else os.environ.get('NOVA_DEV_KEY')
        if not key:
            if not sys.stdin.isatty():raise RuntimeError('USE_PRIVATE_TERMINAL_FOR_KEY')
            key=getpass.getpass('NOVA development key (hidden, never saved): ')
        if not key.strip():raise ValueError('KEY_REQUIRED')
        client=Client(api_base='https://nova.snubhai.org',token=key,sample=True)
        ledger=out/'comparison_ledger.json'
        if ledger.exists():
            plan=json.loads(ledger.read_text(encoding='utf-8'))
            if plan['purpose']!=PURPOSE:raise ValueError('LEDGER_PURPOSE_MISMATCH')
        else:
            if a.remaining<6 or a.credit_percent<=0 or not a.no_active_samples:
                raise ValueError('REMAINING_CREDIT_OR_ACTIVE_STATUS_NOT_CONFIRMED')
            # Only the documented case-list route; never touch submissions/evaluations.
            listed=client._request('GET','/v1/sample/cases')
            samples=listed.get('cases',listed.get('samples',[])) if isinstance(listed,dict) else listed
            mapping={}
            for code in CASES:
                local=json.loads((Path(a.samples)/code/'case.json').read_text(encoding='utf-8'))
                opening=local['start_information']['opening']
                matches=[]
                for case in samples:
                    if (case.get('case_code')==code or case.get('code')==code or case.get('case_id')==code
                        or code in str(case.get('title','')).split()
                        or (case.get('initial',case.get('start_information',{})).get('opening')==opening)):
                        matches.append(case)
                if len(matches)!=1:raise ValueError('CASE_MAPPING_UNCONFIRMED_'+code)
                value=matches[0].get('id') or matches[0].get('case_id')
                mapping[code]=str(uuid.UUID(str(value)))
            plan={'purpose':PURPOSE,'max_new_sessions':6,'max_self_reviews':3,
                  'confirmed_remaining_sessions':a.remaining,'confirmed_credit_percent':a.credit_percent,
                  'confirmed_no_active_samples':True,'confirmed_at_utc':datetime.now(timezone.utc).isoformat(),
                  'model':'openai/gpt-6-luna','reasoning_effort':'medium','slots':[]}
            for code in CASES:
                for version,app in [('v3.2',a.baseline),('v3.3',str(ROOT/'app'))]:
                    slot={'case':code,'case_uuid':mapping[code],'version':version,'app':str(Path(app).resolve()),
                          'app_sha256':app_hash(Path(app)),'create_request_id':str(uuid.uuid4()),'status':'NOT_STARTED'}
                    name=f'{code}_{version}.json';save(out/name,slot);plan['slots'].append(name)
            save(ledger,plan)
        if len(plan['slots'])!=6:raise ValueError('SIX_FIXED_SLOTS_REQUIRED')
        for name in plan['slots']:
            path=out/name;row=json.loads(path.read_text(encoding='utf-8'))
            if row['status']=='completed':continue
            if row['status']!='NOT_STARTED':
                if row.get('session_id'):
                    client.session_id=row['session_id']
                    remote=client.session();row['reconciled_remote_status']=remote.get('status');save(path,row)
                elif row['status'] in ('CREATE_PENDING','REQUIRES_RECONCILIATION'):
                    # Idempotent reconciliation: same case AND original request id, never a new slot.
                    remote=client.create_sample(row['case_uuid'],request_id=row['create_request_id'])
                    row['session_id']=remote['session_id'];row['reconciled_remote_status']=remote.get('status');save(path,row)
                raise RuntimeError('EXISTING_SLOT_REQUIRES_REVIEW_NO_NEW_SESSION')
            if app_hash(Path(row['app']))!=row['app_sha256']:raise ValueError('PINNED_APP_CHANGED')
            print('Running',row['case'],row['version'],flush=True)
            # A child imports only one version. Credential passes through an anonymous pipe.
            command=[sys.executable,'-B','-I',str(Path(__file__).resolve()),'--worker','--app',row['app'],'--entry',str(path)]
            run=subprocess.run(command,input=key+'\n',text=True,encoding='utf-8',timeout=2460)
            if run.returncode:raise RuntimeError('RUN_FAILED_STOP_AND_REVIEW')
        print('Six fixed slots completed. Raw results remain outside Git.',flush=True)
        return 0
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--app');p.add_argument('--entry')
    p.add_argument('--baseline');p.add_argument('--samples');p.add_argument('--output')
    p.add_argument('--key-stdin',action='store_true',help='Read key from a trusted launcher anonymous pipe; never from a file')
    p.add_argument('--remaining',type=int,default=0);p.add_argument('--credit-percent',type=float,default=0)
    p.add_argument('--no-active-samples',action='store_true');a=p.parse_args()
    try:raise SystemExit(worker(a) if a.worker else main(a))
    except Exception as exc:
        # Exception code/type only; no response body, credential, URL with secrets, or traceback.
        print('STOP:',getattr(exc,'code',str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__),flush=True)
        raise SystemExit(1)
