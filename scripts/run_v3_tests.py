"""All preserved suites plus v3 regressions, with socket access disabled."""
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts'),str(ROOT/'app')]

def main():
    if sys.version_info[:2]!=(3,12):raise RuntimeError('PYTHON_312_REQUIRED')
    required=['run.py','nova_sdk.py','indexes/bm25_ko.json.gz','assets/research_policy.json','assets/evidence_units.json']
    missing=[n for n in required if not (ROOT/'app'/n).is_file()]
    if missing:raise FileNotFoundError('MISSING_REQUIRED_APP_INPUTS: '+', '.join(missing))
    out=ROOT/'reports/v3_test_runs'/uuid.uuid4().hex/'results.json'
    out.parent.mkdir(parents=True,exist_ok=False)
    os.environ['NOVA_TEST_OUTPUT_DIR']=str(out.parent/'synthetic')
    modules=['test_agent','test_regressions','test_sample_runner','test_followup',
        'test_transport_diagnostics','test_key_input','test_budget_v3','test_record_budget','test_action_repair',
        'test_final_sample_runner']
    suites={m:unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(m)) for m in modules}
    counts={m:s.countTestCases() for m,s in suites.items()}
    start=time.monotonic()
    with patch.object(socket,'socket',side_effect=AssertionError('NETWORK_DISABLED')), \
         patch.object(socket,'getaddrinfo',side_effect=AssertionError('NETWORK_DISABLED')), \
         patch.object(socket,'create_connection',side_effect=AssertionError('NETWORK_DISABLED')):
        result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites.values()))
    report={'tests':result.testsRun,'passed':result.wasSuccessful(),'counts_by_module':counts,
        'failures':len(result.failures),'errors':len(result.errors),'python':sys.version,
        'elapsed_seconds':time.monotonic()-start,'synthetic_only':True,'real_server_calls':0,
        'network_guard':'Python socket, getaddrinfo, create_connection patched; not OS network namespace',
        'diagnosis_accuracy_evaluated':False,'clinical_record_quality_evaluated':False}
    import test_record_budget
    scenarios=out.parent/'record_headroom_scenarios.json'
    scenarios.write_text(json.dumps({'synthetic_only':True,'real_server_calls':0,
        'scenarios':test_record_budget.SCENARIOS},ensure_ascii=False,indent=2),encoding='utf-8')
    report['record_headroom_scenarios']=str(scenarios)
    import test_action_repair
    repair_scenarios=out.parent/'action_repair_scenarios.json'
    repair_scenarios.write_text(json.dumps({'synthetic_only':True,'real_server_calls':0,
        'scenarios':test_action_repair.SCENARIOS},ensure_ascii=False,indent=2),encoding='utf-8')
    report['action_repair_scenarios']=str(repair_scenarios)
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(out),'tests':result.testsRun,'passed':result.wasSuccessful()}))
    return int(not result.wasSuccessful())

if __name__=='__main__':sys.exit(main())
