"""New consultation protocol plus RAG/workflow regressions, all network blocked."""
import argparse
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'tests'), str(ROOT / 'scripts')]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--report', required=True)
    a = p.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('PYTHON_312_REQUIRED')
    target = Path(a.report)
    if target.exists():
        raise FileExistsError('KEEP_EXISTING_OFFLINE_REPORT')
    names = ('test_consultation_v34', 'test_extension', 'test_comparison_workflow')
    with patch.dict(os.environ, {'NOVA_RAG_SOURCES': 'legacy'}), \
         patch.object(socket, 'socket', side_effect=AssertionError('NETWORK_DISABLED')), \
         patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NETWORK_DISABLED')), \
         patch.object(socket, 'create_connection', side_effect=AssertionError('NETWORK_DISABLED')):
        suites = {name: unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)) for name in names}
        counts = {name: suite.countTestCases() for name, suite in suites.items()}
        started = time.monotonic()
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites.values()))
    report = {'tests': result.testsRun, 'passed': result.wasSuccessful(), 'counts_by_module': counts,
        'failures': len(result.failures), 'errors': len(result.errors), 'elapsed_seconds': time.monotonic() - started,
        'python': sys.version, 'real_api_calls': 0, 'synthetic_only': True,
        'new_protocol_enabled_in_consultation_and_production_entry_tests': True,
        'network_guard': 'Python socket/getaddrinfo/create_connection blocked; not OS container isolation',
        'clinical_quality_or_score_improvement_verified': False}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    raise SystemExit(main())
