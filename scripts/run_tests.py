import json
import os
import socket
import sys
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))

def main():
    app = Path(os.environ.get('NOVA_TEST_APP', str(ROOT/'app')))
    required = ['run.py', 'nova_sdk.py', 'indexes/bm25_ko.json.gz', 'assets/research_policy.json', 'assets/evidence_units.json']
    missing = [name for name in required if not (app/name).is_file()]
    if missing:
        raise FileNotFoundError('MISSING_REQUIRED_APP_INPUTS: ' + ', '.join(missing))
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]
    path = Path(os.environ.get('NOVA_TEST_REPORT', str(ROOT/'reports/test_runs'/run_id/'results.json')))
    if path.exists():
        raise FileExistsError('KEEP_EXISTING_TEST_REPORT: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ['NOVA_TEST_OUTPUT_DIR'] = str(path.parent/run_id)
    Path(os.environ['NOVA_TEST_OUTPUT_DIR']).mkdir(parents=True, exist_ok=False)
    import test_agent,test_regressions,test_sample_runner
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in [test_agent,test_regressions,test_sample_runner]])
    started=time.monotonic()
    with patch.object(socket,'socket',side_effect=AssertionError('NETWORK_DISABLED')),patch.object(socket,'getaddrinfo',side_effect=AssertionError('NETWORK_DISABLED')),patch.object(socket,'create_connection',side_effect=AssertionError('NETWORK_DISABLED')):
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    path.write_text(json.dumps({'tests':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),
        'python':sys.version,'elapsed_seconds':time.monotonic()-started,'network_guard':'socket/socket.getaddrinfo/create_connection disabled',
        'synthetic_only':True,'real_server_calls':0,'clinical_accuracy_evaluated':False,'loop_scenarios':test_agent.REPORTS},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(path),'tests':result.testsRun,'passed':result.wasSuccessful()},ensure_ascii=True))
    return int(not result.wasSuccessful())

if __name__=='__main__':sys.exit(main())
