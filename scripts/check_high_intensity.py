"""Explicit H1-H4 exception policy on the pinned, unchanged offline harness.

Only Run.doctor may differ among the original protected symbols. Its exact
auxiliary-call extension is checked against a transformation of v3.5; this is
not a general opt-out from the model, transport or final-record guards.
"""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '81714d340207a8e5ca9886dd2129cbd6b9cc61f2'
HARNESS = '93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c'
APP_CHANGES = {'app/nova_agent/loop.py', 'app/nova_agent/clinical_strategy.py',
               'app/nova_agent/experiment_config.py'}
COMMON = ['action_observation_delivery', 'final_record_budget', 'accounting',
          'repair', 'evaluator_separation']
BASELINE_LOOP_SOURCE = None
HARNESS_MODULE = None


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def load_harness(root):
    if git(root, 'rev-parse', 'HEAD').decode().strip() != HARNESS:
        raise ValueError('PINNED_HARNESS_COMMIT_REQUIRED')
    for name in ('scripts/dev_harness.py', 'harness/baselines.json'):
        if (root / name).read_bytes() != git(root, 'show', HARNESS + ':' + name):
            raise ValueError('MODIFIED_HARNESS_REFUSED')
    spec = importlib.util.spec_from_file_location('pinned_dev_harness', root / 'scripts/dev_harness.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def function_node(source, name, owner=None):
    tree = ast.parse(source)
    nodes = tree.body if owner is None else next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner).body
    matches = [n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise ValueError('MISSING_OR_DUPLICATE_PROTECTED_FUNCTION')
    return matches[0]


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('DECLARED_DOCTOR_EXTENSION_NO_LONGER_MATCHES_BASELINE')
    return source.replace(old, new)


def expected_doctor(baseline):
    # All untouched statements are inherited from the pinned Git baseline.
    # Every replacement is explicit, including auxiliary no-retry and timeout.
    node = function_node(baseline, 'doctor', 'Run')
    source = textwrap.dedent(ast.get_source_segment(baseline, node))
    replacements = (
        ('def doctor(self, system, user, final=False):',
         "def doctor(self, system, user, final=False, purpose='ACTION'):\n"
         "        if purpose not in ('ACTION', 'PLAN', 'AUDIT') or (final and purpose != 'ACTION'):\n"
         "            raise ValueError('INVALID_DOCTOR_PURPOSE')"),
        ('cfg, report = self.config, self.report',
         "cfg, report = self.config, self.report\n        auxiliary = purpose != 'ACTION'"),
        ('limit = 4096 if final else 2048',
         "limit = 4096 if final else 2048\n        effort = 'medium'\n        if auxiliary:\n"
         '            limit, effort = call_settings(self.state.strategy, purpose, self.left() - cfg.time_margin)'),
        ("[messages, limit, MODEL, 'medium']", '[messages, limit, MODEL, effort]'),
        ('for attempt in range(cfg.attempts):', 'for attempt in range(1 if auxiliary else cfg.attempts):'),
        ("phase='RECORD' if final else 'ACTION'", "phase='RECORD' if final else purpose"),
        ('self.client.timeout = max(1, min(240, self.left() - 5))',
         "self.client.timeout = max(1, min(240, self.left() - 5))\n                if auxiliary:\n"
         "                    self.client.timeout = max(1, min(180 if effort == 'high' else 120, self.left() - cfg.time_margin))"),
        ("reasoning_effort='medium'", 'reasoning_effort=effort'),
        ('if exc.code not in TRANSIENT or attempt + 1 == cfg.attempts:',
         'if auxiliary or exc.code not in TRANSIENT or attempt + 1 == cfg.attempts:'),
    )
    for old, new in replacements:
        source = replace_once(source, old, new)
    return ast.parse(source).body[0]


def verify_loop(h, source, baseline):
    name = 'app/nova_agent/loop.py'
    before = h.protected_signature(baseline, name)
    after = h.protected_signature(source, name)
    for symbol in before:
        if symbol != 'doctor' and before[symbol] != after[symbol]:
            raise ValueError('PROTECTED_SYMBOL_CHANGE:' + symbol)
    if ast.dump(function_node(source, 'doctor', 'Run')) != ast.dump(expected_doctor(baseline)):
        raise ValueError('DOCTOR_EXTENSION_OUTSIDE_EXACT_POLICY')
    # The unchanged transport method remains the sole model-call location.
    tree = ast.parse(source)
    doctor = function_node(source, 'doctor', 'Run')
    chats = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'chat']
    doctor_chats = [n for n in ast.walk(doctor) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'chat']
    if len(chats) != 1 or [ast.dump(n) for n in chats] != [ast.dump(n) for n in doctor_chats]:
        raise ValueError('MODEL_CALL_OUTSIDE_PROTECTED_DOCTOR')
    constants = {'TRANSIENT', 'REGENERATE', 'CLOSED', 'TURN_REJECTIONS'}
    def declarations(text):
        return {t.id: ast.dump(n) for n in ast.parse(text).body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name) and t.id in constants}
    if declarations(source) != declarations(baseline):
        raise ValueError('PROTECTED_ERROR_CONTRACT_CHANGE')


def verify_new_modules(strategy, config):
    cfg = ast.parse(config)
    assignments = [n for n in cfg.body if not (isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    expected = ast.parse("STRATEGY = 'BASELINE'").body
    if [ast.dump(n) for n in assignments] != [ast.dump(n) for n in expected]:
        raise ValueError('REPOSITORY_DEFAULT_MUST_BE_BASELINE')
    pinned_settings = ast.parse("""
FEATURES = {'BASELINE': (), 'H1': ('planner',), 'H2': ('examination',),
            'H3': ('audit',), 'H4': ('planner', 'examination', 'audit')}
def features(strategy):
    if strategy not in FEATURES:
        raise ValueError('UNKNOWN_CLINICAL_STRATEGY')
    return FEATURES[strategy]
def call_settings(strategy, purpose, seconds_left):
    enabled = features(strategy)
    if purpose == 'PLAN' and 'planner' in enabled:
        return 3072, 'medium'
    if purpose == 'AUDIT' and 'audit' in enabled:
        return (4096, 'high') if strategy == 'H4' and seconds_left > 300 else (3072, 'medium')
    raise ValueError('AUXILIARY_PURPOSE_NOT_ENABLED')
""").body
    def protected_settings(tree):
        return [n for n in tree if (isinstance(n, ast.FunctionDef) and n.name in {'features', 'call_settings'})
                or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FEATURES' for t in n.targets))]
    if [ast.dump(n) for n in protected_settings(ast.parse(strategy).body)] != [ast.dump(n) for n in pinned_settings]:
        raise ValueError('AUXILIARY_SETTINGS_OUTSIDE_EXACT_POLICY')
    # New helper code cannot introduce a second transport or execute/import
    # evaluator material. Clinical meaning still needs human/model review.
    for n in ast.walk(ast.parse(strategy)):
        if isinstance(n, ast.Call):
            called = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else None
            if called in {'chat', 'session', 'say', 'exam', 'diagnose', 'eval', 'exec', '__import__'}:
                raise ValueError('STRATEGY_TRANSPORT_OR_DYNAMIC_EXECUTION_FORBIDDEN')


def verify_scope(h, changes, known, snapshot):
    if set(changes) - APP_CHANGES:
        raise ValueError('HIGH_INTENSITY_APP_SCOPE_VIOLATION')
    if h.scope_status(changes, known, True) == 'FAIL' or any(v == 'SYMLINK' for v in snapshot.values()):
        raise ValueError('ORIGINAL_HARNESS_SCOPE_VIOLATION')


def policy(h, repo=ROOT):
    global BASELINE_LOOP_SOURCE
    changes, known, snapshot = h.changed_app(repo, 'v3.5')
    verify_scope(h, changes, known, snapshot)
    BASELINE_LOOP_SOURCE = git(repo, 'show', BASELINE + ':app/nova_agent/loop.py').decode('utf-8')
    verify_loop(h, (repo / 'app/nova_agent/loop.py').read_text(encoding='utf-8'), BASELINE_LOOP_SOURCE)
    name = 'app/nova_agent/prompts.py'
    if h.protected_signature((repo / name).read_bytes(), name) != h.protected_signature(git(repo, 'show', BASELINE + ':' + name), name):
        raise ValueError('PROTECTED_RECORD_CHANGE')
    verify_new_modules((repo / 'app/nova_agent/clinical_strategy.py').read_text(encoding='utf-8'),
                       (repo / 'app/nova_agent/experiment_config.py').read_text(encoding='utf-8'))
    return {'status': 'REVIEW', 'automatic_policy': 'PASS', 'explicit_app_allowlist': sorted(APP_CHANGES),
            'actual_app_changes': changes, 'protected_ast': 'PASS',
            'explicit_symbol_exception': 'Run.doctor: exact auxiliary-call extension only',
            'doctor_invariants': {'baseline_action': '2048/medium', 'record': '4096/medium',
                'auxiliary_http_attempts_per_invocation': 1, 'planner': '3072/medium',
                'audit': '3072/medium; H4 only 4096/high with >300 seconds beyond final time margin',
                'reservation_and_settlement': 'identical v3.5 statements',
                'final_record_envelope': 'identical v3.5 statements'},
            'baseline_commit': BASELINE, 'harness_commit': HARNESS, 'app_snapshot': snapshot,
            'clinical_quality': 'NOT_EVALUATED'}


def main():
    global HARNESS_MODULE
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--harness', type=Path, default=ROOT.parent / 'nova-medical-agent-harness')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--worker', action='store_true')
    p.add_argument('--strategy-only', action='store_true')
    p.add_argument('--test', action='append', help='Narrow affected test rerun; omits common groups')
    a = p.parse_args()
    if sys.version_info[:2] != (3, 12):
        p.error('Python 3.12 required')
    h = load_harness(a.harness.resolve())
    HARNESS_MODULE = h
    report = policy(h)
    out = a.output.resolve()
    if ROOT.is_relative_to(out) or any(out.is_relative_to(ROOT / x) for x in ('app', '.git', 'tests', 'scripts', 'harness')):
        raise ValueError('OUTPUT_OVERLAPS_SOURCE')
    if a.worker:
        if out.exists():
            raise ValueError('WORKER_OUTPUT_MUST_BE_NEW')
        if a.test and any(not t.startswith(('test_high_intensity.', 'test_high_intensity_policy.')) for t in a.test):
            raise ValueError('ONLY_HIGH_INTENSITY_TEST_SELECTION_ALLOWED')
        # Make the already-verified baseline available to policy mutation tests;
        # no Git subprocess is permitted after h.worker installs its audit hook.
        sys.modules['check_high_intensity'] = sys.modules[__name__]
        h.GROUPS['high_intensity'] = a.test or ['test_high_intensity', 'test_high_intensity_policy']
        groups = [] if a.strategy_only or a.test else COMMON
        return h.worker(ROOT, out, groups + ['high_intensity'])
    out.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not (k.startswith('NOVA_') or any(x in k.upper() for x in ('TOKEN', 'API_KEY', 'SECRET')))}
    cmd = [sys.executable, '-X', 'utf8', '-B', '-I', __file__, '--harness', str(a.harness), '--worker', '--output', str(out / 'worker')]
    if a.strategy_only:
        cmd.append('--strategy-only')
    for test in a.test or []:
        cmd += ['--test', test]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8', timeout=240)
    (out / 'tests.log').write_text(result.stderr, encoding='utf-8', newline='\n')
    testfile = out / 'worker/tests.json'
    report['regressions'] = json.loads(testfile.read_text(encoding='utf-8')) if testfile.exists() else {'status': 'FAIL', 'reason': 'worker failed; see tests.log'}
    if result.returncode:
        report['regressions']['status'] = 'FAIL'
    report['app_preserved'] = report['app_snapshot'] == h.changed_app(ROOT, 'v3.5')[2]
    if not report['app_preserved'] or report['regressions']['status'] == 'FAIL':
        report['status'] = 'FAIL'
    (out / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'status': report['status'], 'report': str(out / 'validation.json')}))
    return int(report['status'] == 'FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
