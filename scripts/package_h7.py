"""Package one pinned candidate with a paired executor ablation and mock each extracted run.py; no live APIs."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_h7 import ROOT, BASELINE, APP_CHANGES, git, load_harness, policy

NAMES = {'H7': 'closed_loop_executor'}
AUX_CAPS = {'H7': 1}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8', newline='\n')


def smoke(a, h):
    app = a.app.resolve()
    os.environ['NOVA_TEST_APP'] = str(app)
    os.environ['NOVA_RAG_SOURCES'] = 'legacy'
    sys.path[:0] = [str(app), str(ROOT / 'tests')]
    sys.addaudithook(lambda event, args: h.guard_event(event, args, a.output.resolve()))
    import nova_agent
    import nova_sdk
    from nova_agent.experiment_config import STRATEGY
    from nova_agent.closed_loop import GoalExecutor, GOALS
    from nova_agent.prompts import RECORD
    from test_h7 import counterfactual_scenario
    from contextlib import nullcontext
    assert STRATEGY == a.smoke == 'H7'
    assert Path(nova_agent.__file__).resolve().is_relative_to(app)
    assert Path(nova_sdk.__file__).resolve().is_relative_to(app)
    results = {}
    for enabled in (True, False):
        client, primary = counterfactual_scenario()
        captured = []
        original = nova_agent.prepare
        def prepare():
            state = original()
            captured.append(state)
            return state
        ablation = nullcontext() if enabled else patch.object(GoalExecutor, 'choose', return_value=None)
        with ablation, patch.object(nova_sdk, 'Client', return_value=client), patch.object(nova_agent, 'prepare', side_effect=prepare):
            runpy.run_path(str(app / 'run.py'), run_name='__main__')
        state = captured[0]
        report = state.report
        assert state.strategy == 'H7' and state.config.max_turns == 40
        assert state.config.max_doctor_requests == 80 and state.config.max_input_budget == 500000
        assert state.config.max_output_budget == 100000 and state.config.time_margin == 300
        assert report['termination_reason'] == 'DOCTOR_DONE'
        assert report['record_outcome'] == 'DOCTOR_RECORD_VALIDATED'
        assert report['invalid_model_outputs'] == 0
        assert not report['patient_understanding_assessed']
        assert not report['budget_ledger']['official_or_configured_limit_exceeded']
        assert len(client.submissions) == 1
        assert not any(c['action'] == 'TEST' for c in client.calls)
        counts = Counter(r['phase'] for r in report['budget_ledger']['requests'])
        assert counts['GOALS'] == 1 and counts['RECORD'] == 1
        assert counts['ACTION'] == (5 if enabled else 2)
        assert report['goal_plan_events'][0]['http_attempts'] == 1
        assert primary[0] == 'ASK' and all(action == 'DONE' for action in primary[1:])
        assert report['closed_loop']['supplements'] == (3 if enabled else 0)
        assert report['actions_succeeded'] == (4 if enabled else 1)
        assert report['acknowledged_explanations'] == int(enabled)
        assert all(g['execution'] == ('performed' if enabled else 'pending') for g in report['closed_loop']['goals'])
        note = client.submissions[0]['note']
        assert note['O']['tests'] == ''
        if enabled:
            assert [g['receipts'][0]['observation_id'] for g in report['closed_loop']['goals']] == ['F3', 'F4', 'F5']
            assert '약은 먹지만 이름은 몰라요' in note['S']['hpi']
            assert '무슨 뜻인가요?' in note['S']['hpi']
            assert '복부 반발통 확인' in note['O']['exam']
            assert '[실제 SAY 설명]' in note['P']['education']
        else:
            assert '복부 반발통 확인' not in note['O']['exam']
            assert '[실제 SAY 설명]' not in note['P']['education']
        records = [b for b in client.chat_bodies if b['messages'][0]['content'] == RECORD]
        assert len(records) == 1 and 'closed_loop_not_patient_facts' not in records[0]['messages'][1]['content']
        assert all(b['reasoning_effort'] == 'medium' for b in client.chat_bodies)
        assert all(b['max_tokens'] == (4096 if b['messages'][0]['content'] in (GOALS, RECORD) else 2048) for b in client.chat_bodies)
        results['enabled' if enabled else 'disabled_control'] = {
            'status': 'PASS', 'primary_doctor_choices': primary, 'config': vars(state.config),
            'http_calls_mock': report['doctor_http_attempts'], 'phases': dict(counts),
            'successful_actions': report['action_counts'], 'closed_loop': report['closed_loop'],
            'done_decisions': report['done_decisions'], 'acknowledged_explanations': report['acknowledged_explanations'],
            'record_prompt_sha256': sha(RECORD.encode()),
            'record_context_sha256': sha(records[0]['messages'][1]['content'].encode()),
            'input_bytes': [sum(len(m['content'].encode()) for m in b['messages']) for b in client.chat_bodies],
            'output_caps': [b['max_tokens'] for b in client.chat_bodies],
            'budget': report['budget_ledger'], 'clinical_quality': 'NOT_EVALUATED'}
    save(a.output / 'smoke.json', {'status': 'PASS', 'strategy': 'H7',
        'entrypoint': 'extracted run.py -> real prepare/consult/SDK; offline transport',
        'comparison': results, 'record_prompt_sha256': results['enabled']['record_prompt_sha256'],
        'real_api_calls': 0, 'new_clinical_sessions': 0, 'clinical_quality': 'NOT_EVALUATED',
        'limitation': 'Identical scripted goals and need judgments; after the first question the primary Doctor chooses DONE only. The control disables only GoalExecutor.choose. This isolates execution, not medical judgment.'})


def package_one(strategy, label, payloads, out, env):
    target = out / f'nova_doctor_bm25_candidate_{strategy}_{label}_20261022.zip'
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, original in sorted(payloads.items()):
            data = original
            if name == 'nova_agent/experiment_config.py':
                assert data.count(b"STRATEGY = 'BASELINE'") == 1
                data = data.replace(b"STRATEGY = 'BASELINE'", f"STRATEGY = '{strategy}'".encode())
            if name.endswith('.py'):
                compile(data, name, 'exec')
            info = zipfile.ZipInfo(name, (2026, 10, 22, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    size = target.stat().st_size
    assert size < 45000000, 'H7_45MB_TARGET'
    stage = out / strategy
    stage.mkdir()
    files = []
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(payloads) and set(z.namelist()) == set(payloads)
        assert {'run.py', 'requirements.txt'} <= set(z.namelist())
        assert len(z.namelist()) < 5000
        assert sum(i.file_size for i in z.infolist()) < 500000000
        for name in z.namelist():
            dest = (stage / 'app' / name).resolve()
            assert dest.is_relative_to((stage / 'app').resolve())
            data = z.read(name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            files.append({'path': name, 'sha256': sha(data), 'bytes': len(data)})
    result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-I', __file__,
                             '--smoke', strategy, '--app', str(stage / 'app'),
                             '--output', str(stage)], env=env, capture_output=True,
                            text=True, encoding='utf-8', timeout=240)
    (stage / 'smoke.log').write_text(result.stderr, encoding='utf-8', newline='\n')
    if result.returncode:
        raise RuntimeError('EXTRACTED_ENTRYPOINT_FAILED:' + strategy + '\n' + result.stderr[-3000:])
    for row in files:
        assert sha((stage / 'app' / row['path']).read_bytes()) == row['sha256']
    entry = {'candidate': strategy + '_' + label, 'strategy': strategy,
             'baseline_commit': BASELINE, 'path': str(target), 'bytes': size,
             'sha256': sha(target.read_bytes()), 'below_45mb_target': size < 45000000,
             'changed_app_files': sorted(APP_CHANGES), 'max_auxiliary_http_calls': AUX_CAPS[strategy],
             'files': files, 'smoke': json.loads((stage / 'smoke.json').read_text(encoding='utf-8')),
             'clinical_quality': 'NOT_EVALUATED'}
    save(stage / 'candidate.json', entry)
    print(json.dumps({'candidate': strategy, 'bytes': size, 'smoke': 'PASS'}), flush=True)
    return entry


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--validation', type=Path)
    p.add_argument('--smoke', choices=NAMES)
    p.add_argument('--app', type=Path)
    a = p.parse_args()
    h = load_harness(ROOT.parent / 'nova-medical-agent-harness')
    if a.smoke:
        if not a.app:
            p.error('--app required for extracted smoke')
        smoke(a, h)
        return
    if not a.validation:
        p.error('--validation required before packaging')
    validation_bytes = a.validation.read_bytes()
    validation = json.loads(validation_bytes)
    if validation.get('status') not in {'PASS', 'REVIEW'}:
        raise ValueError('PASSING_AUTOMATIC_VALIDATION_REQUIRED')
    check = policy(h)
    if validation.get('app_snapshot') != check['app_snapshot']:
        raise ValueError('VALIDATION_DOES_NOT_MATCH_CURRENT_APP_BYTES')
    out = a.output.resolve()
    if out.is_relative_to(ROOT):
        raise ValueError('DELIVERABLES_MUST_BE_OUTSIDE_GIT_WORKTREE')
    out.mkdir(parents=True, exist_ok=False)
    base_paths = git(ROOT, 'ls-tree', '-r', '--name-only', BASELINE, 'app/').decode().splitlines()
    # Read and compare baseline blobs only once for the independent archive.
    payloads = {}
    for name in sorted(set(base_paths) | APP_CHANGES):
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or not name.startswith('app/'):
            raise ValueError('INVALID_APP_FILE')
        data = path.read_bytes()
        if name in base_paths and name not in APP_CHANGES:
            assert data == git(ROOT, 'show', BASELINE + ':' + name), name
        payloads[name[4:]] = data
    env = {k: v for k, v in os.environ.items() if not (k.startswith('NOVA_') or
           any(t in k.upper() for t in ('TOKEN', 'API_KEY', 'SECRET')))}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = [pool.submit(package_one, strategy, label, payloads, out, env)
                   for strategy, label in NAMES.items()]
        candidates = [future.result() for future in pending]
    assert len({c['sha256'] for c in candidates}) == 1
    assert len({c['smoke']['record_prompt_sha256'] for c in candidates}) == 1
    assert check['app_snapshot'] == h.changed_app(ROOT, 'v3.5')[2]
    save(out / 'manifest.json', {'status': 'PASS', 'clinical_quality': 'NOT_EVALUATED',
         'baseline_commit': BASELINE, 'policy': check,
         'validation_report': str(a.validation.resolve()), 'validation_sha256': sha(validation_bytes),
         'candidates': candidates})


if __name__ == '__main__':
    main()
