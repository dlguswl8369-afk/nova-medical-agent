"""Official development samples only; persistent limit of three creation attempts."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
import urllib.error
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
sys.path.insert(0,str(ROOT/'scripts'))
from nova_sdk import Client,NovaError
from nova_agent import prepare,consult
from sample_audit import SampleAudit

def safe_code(code):
    return code if isinstance(code,str) and re.fullmatch('[A-Z_]{1,80}',code) else 'UNCLASSIFIED_API_ERROR'


def validate_development_key(token):
    # Reject invalid header input before any request. Never normalize or print it.
    if not isinstance(token,str) or not token:
        raise NovaError('LOCAL_KEY_EMPTY')
    if not token.isascii():
        raise NovaError('LOCAL_KEY_NON_ASCII')
    if any(ord(c)<33 or ord(c)>126 for c in token):
        raise NovaError('LOCAL_KEY_WHITESPACE_OR_CONTROL')

def read_ledger(path):
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or data.get('limit')!=3 or not isinstance(data.get('attempts'),list):
        raise NovaError('LOCAL_INVALID_SESSION_LEDGER')
    if len(data['attempts'])>3 or any(not isinstance(a,dict) or not all(isinstance(a.get(k),str) and a[k]
        for k in ('case_id','request_id','time')) for a in data['attempts']):
        raise NovaError('LOCAL_INVALID_SESSION_LEDGER')
    return data


def check_shared_ledger(path):
    anchor=json.loads((ROOT/'reports/final_sample_authorization.json').read_text(encoding='utf-8'))
    if (anchor.get('version')!=1 or anchor.get('purpose')!='final_development_sample'
            or anchor.get('expected_attempts')!=2 or anchor.get('additional_attempts')!=1
            or anchor.get('total_limit')!=3):
        raise NovaError('LOCAL_INVALID_SAMPLE_AUTHORIZATION')
    if path.resolve(strict=True)!=Path(anchor['canonical_path']).resolve(strict=True):
        raise NovaError('LOCAL_WRONG_SHARED_LEDGER')
    data=read_ledger(path)
    prefix=data['attempts'][:2]
    digest=hashlib.sha256(json.dumps(prefix,sort_keys=True).encode()).hexdigest()
    entries=[hashlib.sha256(json.dumps(a,sort_keys=True).encode()).hexdigest() for a in prefix]
    if digest!=anchor['history_sha256'] or entries!=anchor['entry_sha256']:
        raise NovaError('LOCAL_SESSION_LEDGER_HISTORY_CHANGED')
    if len(data['attempts'])!=2:
        raise NovaError('LOCAL_FINAL_SAMPLE_ALREADY_ATTEMPTED')
    return data


def reserve_session(path,case_id,expected_attempts=2):
    """Count attempts before sending, including uncertain failures. Never auto-reset."""
    if expected_attempts!=2:
        raise NovaError('LOCAL_INVALID_EXPECTED_ATTEMPTS')
    check_shared_ledger(path)  # Missing files are never initialized.
    lock=path.with_suffix('.lock')
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        raise NovaError('LOCAL_SESSION_LEDGER_LOCKED') from None
    try:
        data=check_shared_ledger(path)  # Recheck both records while holding the exclusive lock.
        if len(data['attempts'])>=3:
            raise NovaError('LOCAL_SAMPLE_SESSION_LIMIT')
        request_id=str(uuid.uuid4())
        data['attempts'].append({'case_id':case_id,'request_id':request_id,'time':datetime.now(timezone.utc).isoformat()})
        # Atomic replacement after durable write; an uncertain POST is never rolled back.
        pending=path.with_suffix('.pending')
        with pending.open('x',encoding='utf-8') as handle:
            handle.write(json.dumps(data,indent=2));handle.flush();os.fsync(handle.fileno())
        os.replace(pending,path)
        return request_id
    finally:
        os.close(fd);lock.unlink()


class CountedClient(Client):
    def __init__(self,token):
        validate_development_key(token)
        super().__init__(api_base='https://nova.snubhai.org',token=token,sample=True)
        self.http_attempts=0;self.counts={};self.last_record_check=None
        self.audit=SampleAudit()
        self.transport_diagnostics=[];self.confirmed_sample_sessions=0
    def _open(self,request):
        row=self.transport_diagnostics[-1]
        row['connection_open_attempted']=True
        try:
            response=super()._open(request)
        except urllib.error.HTTPError as e:
            row.update(http_response_received=True,http_status=e.code)
            raise
        row.update(http_response_received=True,http_status=response.status)
        return response
    def _request(self,method,path,body=None):
        assert path.startswith('/v1/sample/') or path=='/v1/chat/completions'
        self.http_attempts+=1
        operation=(body or {}).get('action','CHAT' if path.endswith('/completions') else method+' '+('sample_session' if '/sessions/' in path else path))
        self.counts[operation]=self.counts.get(operation,0)+1
        trace={'operation':operation,'connection_open_attempted':False,'http_response_received':False,'sdk_response_received':False}
        self.transport_diagnostics.append(trace)
        if path == '/v1/sample/sessions' and method == 'POST':
            self.audit=SampleAudit();self.last_record_check=None
        audit_row=self.audit.chat_request(body) if operation=='CHAT' else None
        started=time.monotonic()
        try:
            response=super()._request(method,path,body)
        except NovaError as e:
            trace.update(error_code=safe_code(e.code),exception_type=type(e).__name__)
            if audit_row is not None:
                audit_row.update(error_code=safe_code(e.code),elapsed_seconds=time.monotonic()-started)
            raise
        except (ValueError,KeyError,TypeError) as e:
            trace.update(error_code='LOCAL_REQUEST_OR_RESPONSE_ERROR',exception_type=type(e).__name__)
            raise
        trace['sdk_response_received']=True
        if operation=='GET /v1/sample/cases':
            cases=response.get('cases') if isinstance(response,dict) else None
            trace['listing_schema']={'response_is_object':isinstance(response,dict),'cases_is_list':isinstance(cases,list),
                'case_count':len(cases) if isinstance(cases,list) else None,
                'every_entry_has_case_id':all(isinstance(c,dict) and isinstance(c.get('case_id'),str) for c in cases) if isinstance(cases,list) else False}
        if path=='/v1/sample/sessions' and method=='POST' and isinstance(response,dict):
            try:
                uuid.UUID(response.get('session_id',''))
            except (ValueError,TypeError,AttributeError):
                trace['valid_session_id_received']=False
            else:
                trace['valid_session_id_received']=True;self.confirmed_sample_sessions+=1
        if audit_row is not None:
            self.audit.chat_response(audit_row,response)
            audit_row['elapsed_seconds']=time.monotonic()-started
        if isinstance(response,dict) and isinstance(response.get('initial'),dict):
            self.audit.initial=response['initial']
        self.audit.action_response(body or {},response)
        if (body or {}).get('action')=='DIAGNOSE':
            note=body['note'];raw=json.dumps(note,ensure_ascii=False).encode('utf-8')
            self.last_record_check={'sdk_validation_passed':True,'server_response_received':True,
                'note_sha256':hashlib.sha256(raw).hexdigest(),'note_bytes':len(raw),'diagnosis_bytes':len(body['diagnosis'].encode('utf-8')),
                'objective_tests_empty':note['O']['tests']=='','fields':{s:list(v) for s,v in note.items()}}
            self.last_record_check.update(self.audit.record_check(note))
            # No undocumented response text or raw payload is logged.
            self.last_record_check['response_is_object']=isinstance(response,dict)
            self.last_record_check['explicit_accepted']=response.get('accepted') if isinstance(response,dict) and type(response.get('accepted')) is bool else None
            self.last_record_check['response_sha256']=hashlib.sha256(json.dumps(response,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return response


def run_samples(client,max_samples=1,case_id=None,ledger=None,prepare_fn=prepare,consult_fn=consult,expected_attempts=2):
    if max_samples!=1:raise NovaError('LOCAL_ONE_ADDITIONAL_SAMPLE_ONLY')
    if ledger is None:raise NovaError('LOCAL_EXPLICIT_SESSION_LEDGER_REQUIRED')
    if expected_attempts!=2:raise NovaError('LOCAL_INVALID_EXPECTED_ATTEMPTS')
    check_shared_ledger(ledger)
    lock=ledger.with_suffix('.run.lock')
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        raise NovaError('LOCAL_SAMPLE_RUN_LOCKED') from None
    try:
        check_shared_ledger(ledger)
        return _run_one_sample(client,case_id,ledger,prepare_fn,consult_fn)
    finally:
        os.close(fd);lock.unlink()


def _run_one_sample(client,case_id,ledger,prepare_fn,consult_fn):
    ids=list(dict.fromkeys(str(c['case_id']) for c in client._request('GET','/v1/sample/cases')['cases']))
    if not ids or (case_id and case_id not in ids):return {'status':'NO_MATCHING_PUBLIC_CASE','cases':[]}
    first=case_id or ids[0]
    ordered=[first]
    report={'status':'COMPLETED_REQUESTED_PUBLIC_SAMPLES','cases':[]}
    for cid in ordered:
        row={'case_id':cid,'submitted':False};report['cases'].append(row)
        started=time.monotonic();before=client.http_attempts
        state=prepare_fn()
        try:
            rid=reserve_session(ledger,cid,expected_attempts=2)
            client.create_sample(cid,request_id=rid)
            consult_fn(client,state)
            row.update(state.report)
            row['record_check']=client.last_record_check
            row['actual_nonempty_reference_delivered']=any(p['body_chars']>0 for p in state.report.get('reference_packets',[]))
            row['both_interview_and_exam_processed']=all(state.report.get('action_counts',{}).get(a,0)>0 for a in ['SAY','EXAM'])
        except NovaError as e:
            row.update(state.report);row['failure_code']=safe_code(e.code)
        except (ValueError,KeyError,TypeError,FileExistsError):
            row.update(state.report);row['failure_code']='INVALID_DATA_OR_BUDGET_LOCK'
        except OSError:
            row.update(state.report);row['failure_code']='LOCAL_TRANSPORT_UNCERTAIN'
        row.update(elapsed_seconds=time.monotonic()-started,http_attempts=client.http_attempts-before)
        if hasattr(client,'audit'):
            row.update(client.audit.report())
            checks=row['doctor_response_checks'];record=row.get('record_check') or {}
            row['transport_and_observation_audit_passed']=(
                any(c.get('transport_succeeded') and c.get('nonempty_reference_count',0)>0 for c in checks)
                and all(c.get('context_present') and c.get('observations_match_sdk_responses') for c in checks)
                and not any(c.get('error_code') or c.get('empty_content') or c.get('reported_truncation') for c in checks)
                and row['performed_say_count']>0 and row['performed_exam_count']>0
                and record.get('server_response_received') and record.get('response_is_object')
                and record.get('explicit_accepted') is not False and record.get('so_matches_observed_fact_rendering')
                and record.get('objective_tests_empty'))
        if not (row.get('successful_execution') and not row.get('diagnosis_unresolved') and row.get('actual_nonempty_reference_delivered') and row.get('both_interview_and_exam_processed') and row.get('record_check',{}) and row.get('transport_and_observation_audit_passed',True)):
            report['status']='STOPPED_AFTER_UNSUCCESSFUL_OR_INCOMPLETE_SAMPLE'
            break
    return report


def main():
    (ROOT/'reports').mkdir(parents=True, exist_ok=True)
    parser=argparse.ArgumentParser();parser.add_argument('--max-samples',type=int,choices=[1],default=1);parser.add_argument('--case')
    parser.add_argument('--ledger',type=Path,required=True,help='Existing canonical v2 session ledger; never copied/reset')
    parser.add_argument('--check-ledger',action='store_true',help='Read-only preflight; no key access or HTTP')
    args=parser.parse_args()
    if args.check_ledger:
        try:
            check_shared_ledger(args.ledger)
            if any(args.ledger.with_suffix(s).exists() for s in ('.lock','.run.lock','.pending')):
                raise NovaError('LOCAL_SESSION_LEDGER_LOCKED')
        except (NovaError,ValueError,KeyError,TypeError,OSError) as e:
            print(json.dumps({'status':'BLOCKED','reason':safe_code(e.code) if isinstance(e,NovaError) else 'LOCAL_AUTHORIZATION_OR_LEDGER_INVALID'}))
            return 2
        print(json.dumps({'status':'READY_FOR_ONE_FINAL_SAMPLE','existing_attempts':2,'remaining':1,'key_read':False,'http_calls':0}))
        return 0
    report={'time':datetime.now(timezone.utc).isoformat(),'key_present':bool(os.getenv('NOVA_DEV_KEY')),
        'status':'NOT_RUN_NO_KEY','cases':[],'real_http_attempts':0,'sample_sessions_created':0,
        'leaderboard_or_upload_calls':0,'clinical_accuracy_evaluated':False,'record_quality_scored':False,
        'sample_session_creation_attempts':0,'confirmed_sample_sessions':0,
        'authorized_additional_creation_attempts':1,'shared_ledger_path':str(args.ledger.resolve()),
        'linux_container_validated':False,'external_submission_rights':'UNCONFIRMED'}
    client=None
    try:
        previous=check_shared_ledger(args.ledger)
        report['cumulative_creation_attempts_before']=len(previous['attempts'])
        if report['key_present']:
            client=CountedClient(os.environ['NOVA_DEV_KEY'])
            report.update(run_samples(client,args.max_samples,args.case,ledger=args.ledger,expected_attempts=2))
    except NovaError as e:
        report.update(status='API_ERROR',failure_code=safe_code(e.code))
    except (ValueError,KeyError,TypeError,OSError) as e:
        report.update(status='INVALID_API_DATA',failure_code='LOCAL_REQUEST_OR_API_DATA_ERROR',exception_type=type(e).__name__)
    finally:
        try:
            report['cumulative_creation_attempts_after']=len(read_ledger(args.ledger)['attempts'])
        except (ValueError,KeyError,TypeError,OSError,NovaError):
            report['cumulative_creation_attempts_after']=None
        if client:
            report.update(real_http_attempts=client.http_attempts,http_attempts_by_operation=client.counts,
                sample_session_creation_attempts=client.counts.get('POST /v1/sample/sessions',0),
                confirmed_sample_sessions=client.confirmed_sample_sessions,
                http_responses_received=sum(t['http_response_received'] for t in client.transport_diagnostics),
                transport_diagnostics=client.transport_diagnostics,
                failure_stage=client.transport_diagnostics[-1]['operation'] if client.transport_diagnostics and report['status'] in ('API_ERROR','INVALID_API_DATA') else None)
            # Actual success is not inferred from creation attempts after failures.
            report.pop('sample_sessions_created',None)
        path=ROOT/'reports'/('public_samples_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':report['status'],'real_http_attempts':report['real_http_attempts'],'report':str(path)},ensure_ascii=True))

if __name__=='__main__':sys.exit(main())
