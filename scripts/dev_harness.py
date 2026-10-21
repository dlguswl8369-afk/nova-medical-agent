"""Offline development checks. No checkout, live executor, API key or model call."""
import argparse
import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {'PASS', 'FAIL', 'REVIEW', 'NOT_EVALUATED'}
BASELINES = json.loads((ROOT / 'harness/baselines.json').read_text(encoding='utf-8'))
EDITABLE = {'app/nova_agent/loop.py', 'app/nova_agent/prompts.py'}
NEW_AGENT_PREFIX = 'app/nova_agent/'
GROUPS = {
    'action_observation_delivery': ['test_simple_v35'],
    'final_record_budget': ['test_record_budget'],
    'accounting': ['test_budget_v3.BudgetTests.test_uncertain_request_keeps_reservation',
                   'test_budget_v3.BudgetTests.test_same_id_retry_no_double_reservation',
                   'test_budget_v3.BudgetTests.test_calls_count_same_id_retries_conservatively',
                   'test_budget_v3.LoopV3Tests.test_budget_stop_is_expected_and_final_call_preserved'],
    'repair': ['test_action_repair.RepairTests.test_nfc_boundary_and_exact_transmitted_string',
               'test_action_repair.RepairTests.test_repairs_do_not_enter_observations_or_final_context'],
    'evaluator_separation': ['test_extension.SeparationTests'],
    'harness': ['test_dev_harness'],
}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def blob_hash(path):
    h = hashlib.sha1(b'blob ' + str(path.stat().st_size).encode() + b'\0')
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def changed_app(repo, baseline):
    """Compare bytes to pinned Git blobs without checking out or copying data."""
    ref = BASELINES[baseline]
    expected = {}
    for row in git(repo, 'ls-tree', '-rz', ref, '--', 'app').split(b'\0'):
        if row:
            meta, path = row.split(b'\t', 1)
            expected[path.decode()] = meta.split()[2].decode()
    if not expected:
        raise ValueError('BASELINE_APP_MISSING')
    actual = {p.relative_to(repo).as_posix(): p for p in (repo / 'app').rglob('*')
              if (p.is_file() or p.is_symlink()) and '__pycache__' not in p.parts}
    changed, snapshot = [], {}
    for name in sorted(set(actual) | set(expected)):
        path = actual.get(name)
        snapshot[name] = None if path is None else 'SYMLINK' if path.is_symlink() else blob_hash(path)
        if snapshot[name] != expected.get(name) or name not in expected:
            changed.append(name)
    return changed, set(expected), snapshot


def scope_status(changes, known, candidate=False):
    allowed = lambda n: n in EDITABLE or (n not in known and n.startswith(NEW_AGENT_PREFIX) and n.endswith('.py'))
    if not changes:
        return 'PASS'
    return 'REVIEW' if candidate and all(allowed(n) for n in changes) else 'FAIL'


def protected_signature(source, path):
    """Pin model/config/transport/budget entry points and RECORD across candidates."""
    tree = ast.parse(source)
    selected = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {'MODEL', 'RECORD'}:
                    selected[target.id] = ast.dump(node)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in {'Config', 'prepare'}:
            selected[node.name] = ast.dump(node)
        if isinstance(node, ast.ClassDef) and node.name == 'Run':
            selected.update({n.name: ast.dump(n) for n in node.body if isinstance(n, ast.FunctionDef)
                             and n.name in {'doctor', 'action', 'left'}})
    required = {'RECORD'} if path.endswith('prompts.py') else {'MODEL', 'Config', 'prepare', 'doctor', 'action', 'left'}
    if set(selected) != required:
        raise ValueError('PROTECTED_SECTION_MISSING')
    return selected


def guard_event(event, args, writable):
    """Process-scoped audit guard; not a hostile-code OS sandbox."""
    if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.exec', 'os.spawn', 'os.posix_spawn'}:
        raise PermissionError('HARNESS_NETWORK_OR_PROCESS_BLOCKED')
    targets = []
    if event == 'open':
        path, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            targets = [path]
    elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'}:
        targets = [args[0]]
    elif event in {'os.rename', 'os.link', 'os.symlink'}:
        targets = list(args[:2])
    for path in targets:
        if not isinstance(path, (str, bytes, os.PathLike)):
            raise PermissionError('HARNESS_FILE_DESCRIPTOR_WRITE_BLOCKED')
        resolved = Path(os.fsdecode(path)).resolve()
        if not resolved.is_relative_to(writable):
            raise PermissionError('HARNESS_WRITE_OUTSIDE_RUN_BLOCKED')


def validate_case(case):
    """Validate traceability and partitioning, not clinical meaning or scores."""
    if case.get('schema_version') != 1 or not case.get('case_id') or not case.get('provenance'):
        raise ValueError('CASE_PROVENANCE_REQUIRED')
    doctor = case.get('doctor_input', {})
    if set(doctor) != {'opening', 'vital_signs', 'observations'}:
        raise ValueError('DOCTOR_INPUT_ALLOWLIST')
    seen = set()
    for observation in doctor['observations']:
        if (set(observation) - {'id', 'kind', 'text', 'question', 'intent'}
                or observation.get('kind') not in {'opening', 'vitals', 'patient_reply', 'exam'}
                or not isinstance(observation.get('text'), str)
                or not observation.get('id') or observation['id'] in seen):
            raise ValueError('INVALID_OBSERVATION_OR_EVALUATOR_LEAK')
        seen.add(observation['id'])
    trace = case.get('trace', [])
    ids = [t['id'] for t in trace]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_TRACE_ID')
    criteria = case.get('criteria', [])
    if not criteria or len({c['id'] for c in criteria}) != len(criteria):
        raise ValueError('CRITERIA_REQUIRED_OR_DUPLICATE')
    for item in criteria:
        if item.get('status') not in STATUSES or item.get('domain') not in {'information', 'communication', 'efficiency', 'safety'}:
            raise ValueError('INVALID_REVIEW_STATUS_OR_DOMAIN')
        if not all(item.get(k) for k in ('applicability', 'review_question', 'reason')):
            raise ValueError('REVIEW_CONTEXT_REQUIRED')
        evidence = item.get('evidence', [])
        if item['status'] != 'NOT_EVALUATED' and not evidence:
            raise ValueError('EVIDENCE_REQUIRED')
        for ref in evidence:
            if ref.get('source') == 'trace' and ref.get('id') in ids:
                continue
            if ref.get('source') == 'record' and ref.get('field') in case.get('final_record', {}):
                continue
            raise ValueError('UNKNOWN_EVIDENCE_REFERENCE')
    return {'case_id': case['case_id'], 'criteria': len(criteria), 'clinical_quality': 'NOT_EVALUATED'}


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append({'status': 'PASS', 'evidence': test.id()})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({'status': 'FAIL', 'evidence': test.id(), 'error_type': err[0].__name__})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({'status': 'FAIL', 'evidence': test.id(), 'error_type': err[0].__name__})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err:
            self.rows.append({'status': 'FAIL', 'evidence': subtest.id(), 'error_type': err[0].__name__})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append({'status': 'NOT_EVALUATED', 'evidence': test.id(), 'reason': reason})


def worker(repo, out, groups):
    # Git and baseline checks happen only in the parent before installing the guard.
    out.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    os.environ.update(NOVA_RAG_SOURCES='legacy', NOVA_TEST_OUTPUT_DIR=str(out / 'synthetic'),
                      TEMP=str(out), TMP=str(out))
    tempfile.tempdir = str(out)
    sys.path[:0] = [str(repo / 'app'), str(repo / 'tests'), str(repo / 'scripts'), str(ROOT / 'tests'), str(ROOT / 'scripts')]
    sys.addaudithook(lambda event, args: guard_event(event, args, out.resolve()))
    suites = {}
    for group in groups:
        names = GROUPS[group]
        suites[group] = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
    counts = {g: s.countTestCases() for g, s in suites.items()}
    import nova_agent.loop as loop
    if not Path(loop.__file__).resolve().is_relative_to(repo / 'app'):
        raise RuntimeError('WRONG_APP_IMPORTED')
    result = unittest.TextTestRunner(verbosity=1, resultclass=EvidenceResult).run(unittest.TestSuite(suites.values()))
    report = {'status': 'PASS' if result.wasSuccessful() else 'FAIL', 'tests': result.testsRun,
              'counts': counts, 'checks': result.rows, 'app_source': str(Path(loop.__file__).resolve()),
              'clinical_quality': 'NOT_EVALUATED', 'real_api_calls': 0}
    (out / 'tests.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return int(not result.wasSuccessful())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['check', 'case-check', '_worker'])
    p.add_argument('--repo', type=Path, default=ROOT)
    p.add_argument('--baseline', choices=sorted(BASELINES), default='v3.5')
    p.add_argument('--candidate', action='store_true')
    p.add_argument('--case', type=Path, default=ROOT / 'harness/cases/example.json')
    p.add_argument('--output', type=Path)
    p.add_argument('--group', choices=sorted(GROUPS), action='append', help='Affected groups only; default is all focused checks')
    a = p.parse_args()
    if sys.version_info[:2] != (3, 12):
        p.error('Python 3.12 required')
    repo = a.repo.resolve()
    if a.command == '_worker':
        return worker(repo, a.output.resolve(), a.group or list(GROUPS))
    if a.command == 'case-check':
        print(json.dumps(validate_case(json.loads(a.case.read_text(encoding='utf-8')))))
        return 0
    out = (a.output or ROOT / 'reports/harness_runs' / uuid.uuid4().hex).resolve()
    if any(out.is_relative_to(repo / name) for name in ('app', '.git', 'tests', 'scripts', 'harness')):
        p.error('Output must not overlap source or configuration directories')
    out.mkdir(parents=True, exist_ok=False)
    changes, known, before = changed_app(repo, a.baseline)
    scope = scope_status(changes, known, a.candidate)
    protected = []
    for path in ('app/nova_agent/loop.py', 'app/nova_agent/prompts.py'):
        try:
            original = protected_signature(git(repo, 'show', BASELINES[a.baseline] + ':' + path), path)
            current = protected_signature((repo / path).read_bytes(), path)
            protected.extend(path + ':' + k for k in original if original[k] != current[k])
        except (ValueError, SyntaxError, OSError):
            protected.append(path + ':unreadable_or_missing_section')
    report = {'baseline': a.baseline, 'baseline_commit': BASELINES[a.baseline],
              'head': git(repo, 'rev-parse', 'HEAD').decode().strip(),
              'mode': 'candidate' if a.candidate else 'baseline',
              'scope': {'status': scope, 'evidence': changes, 'method': 'Git blob hashes including untracked app files'},
              'protected_sections': {'status': 'FAIL' if protected else 'PASS', 'evidence': protected,
                                     'method': 'AST comparison of MODEL/Config/prepare/Doctor/action/deadline and RECORD'},
              'clinical_quality': {'status': 'NOT_EVALUATED', 'evidence': 'No clinical model or website evaluation'},
              'manual_review': {'status': 'REVIEW', 'evidence': 'Clinical adequacy, permissions and external evaluation remain human decisions'}}
    if scope != 'FAIL' and not protected:
        env = {k: v for k, v in os.environ.items() if not (k.startswith('NOVA_') or any(x in k.upper() for x in ('TOKEN', 'API_KEY', 'SECRET')))}
        group_args = [part for g in (a.group or []) for part in ('--group', g)]
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-I', __file__, '_worker', '--repo', str(repo), '--output', str(out / 'worker'), *group_args],
                                 env=env, capture_output=True, text=True, encoding='utf-8', timeout=180)
        (out / 'tests.log').write_text(process.stderr, encoding='utf-8', newline='\n')
        tests_path = out / 'worker/tests.json'
        report['regressions'] = json.loads(tests_path.read_text(encoding='utf-8')) if tests_path.exists() else {'status': 'FAIL', 'evidence': 'worker failed; see tests.log'}
        if process.returncode:
            report['regressions']['status'] = 'FAIL'
        _, _, after = changed_app(repo, a.baseline)
        report['app_preservation'] = {'status': 'PASS' if after == before else 'FAIL', 'evidence': 'All app byte hashes unchanged during run'}
    else:
        report['regressions'] = {'status': 'NOT_EVALUATED', 'evidence': 'Scope mismatch; worker was not started'}
    report['status'] = 'FAIL' if any(v.get('status') == 'FAIL' for v in report.values() if isinstance(v, dict)) else 'REVIEW'
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'status': report['status'], 'report': str(out / 'report.json')}))
    return int(report['status'] == 'FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
