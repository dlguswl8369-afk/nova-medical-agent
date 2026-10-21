"""Narrow batch policy layered on the pinned existing offline harness."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '81714d340207a8e5ca9886dd2129cbd6b9cc61f2'
HARNESS = '93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c'
APP_CHANGES = {'app/nova_agent/loop.py', 'app/nova_agent/experiments.py', 'app/nova_agent/experiment_config.py'}
COMMON = ['action_observation_delivery', 'final_record_budget', 'accounting', 'repair', 'evaluator_separation']
RETRIEVAL = ['test_extension.GuidelineTests',
             'test_agent.AgentTests.test_duplicate_and_oversize_evidence',
             'test_agent.AgentTests.test_explicit_source_llm_restriction',
             'test_agent.AgentTests.test_reference_id_cannot_be_patient_fact']


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def load_harness(root):
    if git(root, 'rev-parse', 'HEAD').decode().strip() != HARNESS:
        raise ValueError('PINNED_HARNESS_COMMIT_REQUIRED')
    for name in ('scripts/dev_harness.py', 'harness/baselines.json'):
        if (root / name).read_bytes() != git(root, 'show', HARNESS + ':' + name):
            raise ValueError('MODIFIED_HARNESS_REFUSED')
    spec = importlib.util.spec_from_file_location('pinned_dev_harness', root / 'scripts/dev_harness.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def policy(h):
    changes, known, snapshot = h.changed_app(ROOT, 'v3.5')
    if set(changes) - APP_CHANGES:
        raise ValueError('BATCH_APP_SCOPE_VIOLATION')
    if h.scope_status(changes, known, True) == 'FAIL':
        raise ValueError('ORIGINAL_HARNESS_SCOPE_VIOLATION')
    for name in ('app/nova_agent/loop.py', 'app/nova_agent/prompts.py'):
        if h.protected_signature((ROOT / name).read_bytes(), name) != h.protected_signature(git(ROOT, 'show', BASELINE + ':' + name), name):
            raise ValueError('PROTECTED_MODEL_BUDGET_SDK_OR_RECORD_CHANGE')
    # Whole prompts.py/context.py/retrieval/assets/index/SDK remain pinned by the
    # tighter file allowlist, beyond the original harness's AST protections.
    if (ROOT / 'app/nova_agent/experiment_config.py').read_text(encoding='utf-8').splitlines()[-1] != "STRATEGY = 'V0'":
        raise ValueError('REPOSITORY_DEFAULT_MUST_BE_V0')
    return {'status': 'REVIEW', 'automatic_policy': 'PASS', 'explicit_app_allowlist': sorted(APP_CHANGES),
            'actual_app_changes': changes, 'protected_ast': 'PASS', 'baseline_commit': BASELINE,
            'harness_commit': HARNESS, 'app_snapshot': snapshot}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--harness', type=Path, default=ROOT.parent / 'nova-medical-agent-harness')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--worker', action='store_true')
    p.add_argument('--strategy-only', action='store_true')
    p.add_argument('--retrieval-only', action='store_true', help='Existing retrieval protections, once for shared implementation')
    p.add_argument('--test', action='append', help='Specific batch test or allowlisted retrieval group after a failure')
    a = p.parse_args(); h = load_harness(a.harness.resolve()); report = policy(h)
    out = a.output.resolve()
    if a.worker:
        if a.test and any(not t.startswith('test_batch_experiments.BatchTests.test_') and t not in RETRIEVAL for t in a.test):
            raise ValueError('ONLY_BATCH_OR_RETRIEVAL_TEST_SELECTION_ALLOWED')
        h.GROUPS['batch'] = RETRIEVAL if a.retrieval_only else a.test or ['test_batch_experiments']
        return h.worker(ROOT, out, ['batch'])
    if any(out.is_relative_to(ROOT / x) for x in ('app', '.git', 'tests', 'scripts')):
        raise ValueError('OUTPUT_OVERLAPS_SOURCE')
    out.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not (k.startswith('NOVA_') or any(x in k.upper() for x in ('TOKEN', 'API_KEY', 'SECRET')))}
    if not a.strategy_only and not a.retrieval_only:
        cmd = [sys.executable, '-X', 'utf8', '-B', '-I', str(a.harness / 'scripts/dev_harness.py'), 'check',
               '--repo', str(ROOT), '--candidate', '--output', str(out / 'common')]
        for group in COMMON:
            cmd += ['--group', group]
        subprocess.run(cmd, env=env, check=True, timeout=240)
        report['common'] = json.loads((out / 'common/report.json').read_text(encoding='utf-8'))
    cmd = [sys.executable, '-X', 'utf8', '-B', '-I', __file__, '--harness', str(a.harness), '--worker', '--output', str(out / 'strategies')]
    if a.retrieval_only:
        cmd.append('--retrieval-only')
    for test in a.test or []:
        cmd += ['--test', test]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8', timeout=180)
    (out / 'strategies.log').write_text(result.stderr, encoding='utf-8', newline='\n')
    testfile = out / 'strategies/tests.json'
    report['strategies'] = json.loads(testfile.read_text(encoding='utf-8')) if testfile.exists() else {'status': 'FAIL', 'reason': 'worker failed'}
    if result.returncode:
        report['strategies']['status'] = 'FAIL'
    report['app_preserved'] = report['app_snapshot'] == h.changed_app(ROOT, 'v3.5')[2]
    if not report['app_preserved'] or report['strategies']['status'] == 'FAIL':
        report['status'] = 'FAIL'
    (out / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'status': report['status'], 'report': str(out / 'validation.json')}))
    return int(report['status'] == 'FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
