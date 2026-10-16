"""One focused regression pass and read-only historical context replay. No APIs."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def smoke(app, strategy):
    os.environ['NOVA_TEST_APP'] = str(app)
    sys.path[:0] = [str(app), str(ROOT / 'tests')]
    import nova_sdk
    from nova_agent import loop
    from test_agent import MockClient, plan
    from test_simple_v35 import Replies, say
    assert Path(loop.__file__).resolve().is_relative_to(app.resolve())
    c = Replies([say('복용 중인 약이 있나요?'), {'action': 'EXAM', 'content': '왼쪽 손목 압통 확인'},
                 say('추가 평가가 필요해요', 'EXPLAIN'), {'action': 'DONE'}, plan()],
                ['약은 먹지만 이름은 몰라요', '무슨 뜻인가요?'])
    with patch.dict(os.environ, {'NOVA_RAG_SOURCES': 'none'}), patch.object(nova_sdk, 'Client', return_value=c):
        runpy.run_path(str(app / 'run.py'), run_name='__main__')
    assert c.chat_number == 5
    assert json.loads(c.prompts[0][1]['content'])['decision_view']['strategy'] == strategy
    assert 'decision_view' not in json.loads(c.prompts[-1][1]['content'])
    assert c.submissions[0]['note']['O']['tests'] == ''
    assert '이해 여부는 미확인' in c.submissions[0]['note']['P']['education']
    assert not any(c['action'] == 'TEST' for c in c.calls)
    return {'strategy': strategy, 'zip_entrypoint': True, 'mock_doctor_calls': 5,
            'mock_actions': ['SAY', 'EXAM', 'SAY', 'DIAGNOSE'], 'real_api_calls': 0}


def replay():
    from nova_agent.strategies import action_facts, decision_view, action_prompt
    from nova_agent.context import visible_facts
    from nova_agent.prompts import STEP
    folder = ROOT.parent / 'nova_extension_work_20261015/private_comparison'
    output = []
    for case in ('C01', 'C10', 'C03'):
        for version in ('v3.2', 'v3.3'):
            path = folder / f'{case}_{version}_private.json'
            if not path.exists():
                output.append({'case': case, 'version': version, 'available': False})
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            facts = data['last_reference_context']['current_patient_observations']
            baseline = visible_facts(facts)
            rows = {}
            for strategy in ('A', 'B', 'C'):
                current = action_facts(facts, strategy, 22000)
                assert all(f in facts for f in current)
                assert current == baseline  # These short historical cases fit in full.
                view = decision_view(current, [], strategy)
                rows[strategy] = {
                    'visible_ids': [f['id'] for f in current],
                    'whole_raw_pairs_preserved': True,
                    'extra_serialized_view_bytes': len(json.dumps({'decision_view': view}, ensure_ascii=False).encode()),
                    'extra_system_utf8_bytes': len(action_prompt(strategy).encode()) - len(STEP.encode()),
                    'clinical_selection_quality': 'requires_real_model_evaluation'}
            output.append({'case': case, 'version': version, 'source': path.name,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'source_kind': 'existing_development_API_log_not_website',
                           'scope': 'captured_final_observations_only', 'strategies': rows})
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--smoke-app', type=Path)
    parser.add_argument('--strategy', choices=['A', 'B', 'C'])
    parser.add_argument('--strategy-tests-only', action='store_true')
    args = parser.parse_args()
    target = Path(args.report)
    if target.exists():
        raise FileExistsError('KEEP_EXISTING_REPORT')
    started = time.monotonic()
    with patch.object(socket, 'socket', side_effect=AssertionError('NETWORK_DISABLED')), \
         patch.object(socket, 'create_connection', side_effect=AssertionError('NETWORK_DISABLED')), \
         patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NETWORK_DISABLED')):
        if args.smoke_app:
            report = smoke(args.smoke_app, args.strategy)
        else:
            sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'tests')]
            os.environ['NOVA_RAG_SOURCES'] = 'legacy'
            names = ['test_strategies', 'test_simple_v35', 'test_record_budget', 'test_action_repair', 'test_extension']
            if args.strategy_tests_only:
                names = ['test_strategies']
            suites = [unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(n)) for n in names]
            counts = dict(zip(names, [s.countTestCases() for s in suites]))
            result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
            report = {'tests': result.testsRun, 'passed': result.wasSuccessful(), 'counts': counts,
                      'failures': len(result.failures), 'errors': len(result.errors),
                      'historical_replay': [] if args.strategy_tests_only else replay(), 'real_api_calls': 0,
                      'model_quality_evaluated': False, 'full_suite': False}
        report['elapsed_seconds'] = time.monotonic() - started
        report['network_guard'] = 'Python socket/getaddrinfo/create_connection blocked; not OS isolation'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8', newline='\n') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'historical_replay'}))
    return int(not report.get('passed', True))


if __name__ == '__main__':
    raise SystemExit(main())
