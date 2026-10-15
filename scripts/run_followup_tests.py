import json
from pathlib import Path
import socket
import sys
import time
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))

def main():
    import test_followup
    suite=unittest.defaultTestLoader.loadTestsFromModule(test_followup)
    start=time.monotonic()
    with patch.object(socket,'socket',side_effect=AssertionError('NETWORK_DISABLED')):
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    out=ROOT/'reports/followup_test_runs'/uuid.uuid4().hex/'results.json';out.parent.mkdir(parents=True,exist_ok=False)
    out.write_text(json.dumps({'tests':result.testsRun,'passed':result.wasSuccessful(),'errors':len(result.errors),
        'failures':len(result.failures),'elapsed_seconds':time.monotonic()-start,'real_server_calls':0,
        'synthetic_only':True,'clinical_accuracy_evaluated':False},indent=2),encoding='utf-8')
    print(json.dumps({'report':str(out),'passed':result.wasSuccessful()}));return int(not result.wasSuccessful())

if __name__=='__main__':sys.exit(main())
