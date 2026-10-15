"""Measure prepare/search without network; OS isolation is reported separately."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))


def peak_memory():
    if sys.platform=='linux':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
        handle=ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb)
        return counters.PeakWorkingSetSize
    return None


def probe():
    from nova_agent import prepare
    from nova_agent.context import reference_packet
    rows=[]
    with patch.object(socket,'socket',side_effect=AssertionError('NETWORK_DISABLED')),patch.object(socket,'getaddrinfo',side_effect=AssertionError('NETWORK_DISABLED')):
        start=time.monotonic();state=prepare();seconds=time.monotonic()-start
        for query in ['fever without cough', '발열 없음 복통', 'hypertension treatment', '고혈압 치료']:
            start=time.monotonic();audit={};packet=reference_packet(state.index,query,audit=audit)
            assert len(json.dumps(packet,ensure_ascii=False))<=12000
            assert all(row['not_current_patient_facts'] for row in packet)
            rows.append({'query':query,'seconds':time.monotonic()-start,'packet_chars':audit['packet_chars'],
                         'documents':[r['document_id'] for r in packet],
                         'guideline_count':sum(r.get('source_role')=='organizer_guideline' for r in packet),
                         'body_chars':audit['body_chars']})
    return {'prepare_seconds':seconds,'peak_process_memory_bytes':peak_memory(),
            'python':sys.version,'platform':sys.platform,'real_api_calls':0,'application_socket_guard':True,
            'os_network_isolation_claimed':False,'guidelines_documents':state.index.guidelines.count,
            'queries':rows,'clinical_relevance_evaluated':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report');a=p.parse_args();result=probe()
    if a.report:Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
