"""Package two pinned candidates and mock each extracted run.py; no live APIs."""
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
from check_workflow import ROOT, BASELINE, APP_CHANGES, git, load_harness, policy

NAMES = {'H5': 'adaptive_clinical_workflow', 'H6': 'coverage_first'}
AUX_CAPS = {'H5': 2, 'H6': 1}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8', newline='\n')


def smoke(a, h):
    # The transport fixture is imported only after the archive app is selected.
    # This also keeps the untouched SDK, prepare, consult and run.py in the path.
    app = a.app.resolve()
    os.environ['NOVA_TEST_APP'] = str(app)
    os.environ['NOVA_RAG_SOURCES'] = 'legacy'
    sys.path[:0] = [str(app), str(ROOT / 'tests')]
    sys.addaudithook(lambda event, args: h.guard_event(event, args, a.output.resolve()))
    import nova_agent
    import nova_sdk
    from nova_agent.experiment_config import STRATEGY
    from test_workflow import WorkflowMockClient
    assert STRATEGY == a.smoke
    assert Path(nova_agent.__file__).resolve().is_relative_to(app)
    assert Path(nova_sdk.__file__).resolve().is_relative_to(app)
    client, verify = smoke_scenario(a.smoke, WorkflowMockClient)
    captured = []
    original = nova_agent.prepare

    def prepare():
        state = original()
        captured.append(state)
        return state

    with patch.object(nova_sdk, 'Client', return_value=client), \
            patch.object(nova_agent, 'prepare', side_effect=prepare):
        runpy.run_path(str(app / 'run.py'), run_name='__main__')
    state = captured[0]
    report = state.report
    details = verify(state, client)
    assert report['termination_reason'] == 'DOCTOR_DONE'
    assert report['record_outcome'] == 'DOCTOR_RECORD_VALIDATED'
    assert report['invalid_model_outputs'] == 0
    assert report['acknowledged_explanations'] == 1
    assert not report['patient_understanding_assessed']
    assert not report['budget_ledger']['official_or_configured_limit_exceeded']
    assert not any(c['action'] == 'TEST' for c in client.calls)
    assert len(client.submissions) == 1
    note = client.submissions[0]['note']
    assert note['O']['tests'] == ''
    assert '[실제 SAY 설명]' in note['P']['education']
    assert '무슨 뜻인가요?' in json.dumps(note, ensure_ascii=False)
    result = {'status': 'PASS', 'strategy': a.smoke, 'entrypoint': 'extracted run.py',
              'sdk': 'extracted unmodified SDK; transport mocked',
              'guard': 'pinned existing harness network/process/write audit hook',
              'model': report['model'], 'config': vars(state.config),
              'max_auxiliary_http_calls': AUX_CAPS[a.smoke],
              'actual_mock_http_calls': report['doctor_http_attempts'],
              'successful_actions': report['action_counts'],
              'termination': report['termination_reason'], 'record': report['record_outcome'],
              'budget': report['budget_ledger'], 'real_api_calls': 0,
              'clinical_quality': 'NOT_EVALUATED', 'patient_understanding': 'NOT_EVALUATED',
              **details}
    save(a.output / 'smoke.json', result)


def smoke_scenario(strategy, client_type):
    from nova_agent.workflow_strategy import PLAN, REFRESH, AUDIT
    from nova_agent.prompts import RECORD
    from test_agent import plan
    from test_simple_v35 import say
    from test_workflow import option

    marker = 'SYNTHETIC_UNPERFORMED_PLAN_DO_NOT_RECORD'
    partial = '약은 먹어요. 이름은 몰라요.'
    normal = 0
    selected_phases = []

    def choose(body):
        nonlocal normal
        system, user = [m['content'] for m in body['messages']]
        context = json.loads(user)
        assert isinstance(context['current_patient_observations'], list)
        if system == PLAN:
            selected_phases.append('PLAN')
            assert strategy == 'H5' and normal == 2 and partial in user
            assert marker not in user
            return {'plan': marker, 'next_action': {'action': 'EXAM', 'content': '복부 반발통 확인'}}
        if system == REFRESH:
            selected_phases.append('REFRESH')
            assert strategy == 'H5' and marker in user
            assert '복부 반발통 확인' in user
            return {'plan': marker + '_UPDATED', 'next_action': say('추가 평가가 필요해요', 'EXPLAIN')}
        if system == AUDIT:
            selected_phases.append('AUDIT')
            assert strategy == 'H6' and marker not in user
            assert 'clinical_plan_not_patient_facts' not in context
            return say('추가 평가가 필요해요', 'EXPLAIN')
        if system == RECORD:
            selected_phases.append('RECORD')
            assert marker not in user
            assert 'clinical_plan_not_patient_facts' not in context
            assert 'last_exam_failure_not_patient_facts' not in context
            return plan()
        selected_phases.append('ACTION')
        normal += 1
        assert normal <= 4, 'UNEXPECTED_ACTION_LOOP'
        if normal == 1:
            return say('복용약을 알려주세요') if strategy == 'H5' else {'next_actions': [option(), option('EXAM', '복부 반발통 확인')]}
        if normal == 2:
            return say('통증은 어디인가요?') if strategy == 'H5' else {'next_actions': [option('EXAM', '복부 반발통 확인', ids=['F2'])]}
        return {'action': 'DONE'}

    client = client_type([choose] * 12, replies=[partial, '무슨 뜻인가요?'])

    def verify(state, c):
        report = state.report
        assert state.strategy == strategy and report['strategy'] == strategy
        assert state.config.max_turns == 30 and state.config.max_doctor_requests == 80
        assert state.config.max_input_budget == 500000 and state.config.max_output_budget == 100000
        counts = Counter(r['phase'] for r in report['budget_ledger']['requests'])
        expected = {'PLAN': int(strategy == 'H5'), 'REFRESH': int(strategy == 'H5'), 'AUDIT': int(strategy == 'H6')}
        assert all(counts[k] == v for k, v in expected.items())
        assert sum(counts[k] for k in expected) == AUX_CAPS[strategy]
        assert counts['RECORD'] == 1 and counts['ACTION'] == 4
        assert len(selected_phases) == sum(counts.values()) == c.chat_number
        for request in report['budget_ledger']['requests']:
            if request['phase'] in expected:
                assert request['attempts'] == 1
        if strategy == 'H6':
            assert report['coverage_choices'].count('FRESH_COVERAGE_ACTION') == 2
        assert report['action_counts'] == {'SAY': 2, 'EXAM': 1}
        assert report['actions_succeeded'] == 3
        assert report['final_http_attempts'] == 1
        note = c.submissions[0]['note']
        assert partial in note['S']['hpi']
        assert marker not in json.dumps(note, ensure_ascii=False)
        assert note['O']['exam'].count('[F1]') == 1
        assert '[F3]' in note['O']['exam']
        assert '복부 반발통 확인' in note['O']['exam']
        assert '복부 압통은 있으나 반발통은 없습니다' in note['O']['exam']
        records = [b for b in c.chat_bodies if b['messages'][0]['content'] == RECORD]
        assert len(records) == 1
        assert all(b['reasoning_effort'] == 'medium' for b in c.chat_bodies)
        return {'mock_phase_sequence': selected_phases, 'mock_phase_counts': dict(counts),
                'actual_auxiliary_http_calls': sum(counts[k] for k in expected),
                'mock_action_selection': 'scripted; not a clinical quality assessment',
                'coverage_choices': report['coverage_choices'],
                'auxiliary_events': report['auxiliary_events'],
                'record_prompt_sha256': sha(RECORD.encode()),
                'record_context_sha256': sha(records[0]['messages'][1]['content'].encode()),
                'note_sha256': sha(json.dumps(note, ensure_ascii=False, sort_keys=True).encode()),
                'request_input_bytes': [sum(len(m['content'].encode()) for m in b['messages']) for b in c.chat_bodies],
                'request_output_caps': [b['max_tokens'] for b in c.chat_bodies],
                'reasoning_efforts': [b['reasoning_effort'] for b in c.chat_bodies]}

    return client, verify


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
    assert size < 50000000, 'OFFICIAL_50MB_LIMIT'
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
    # Read and compare baseline blobs only once for both independent archives.
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
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(package_one, strategy, label, payloads, out, env)
                   for strategy, label in NAMES.items()]
        candidates = [future.result() for future in pending]
    assert len({c['sha256'] for c in candidates}) == 2
    assert len({c['smoke']['record_prompt_sha256'] for c in candidates}) == 1
    assert check['app_snapshot'] == h.changed_app(ROOT, 'v3.5')[2]
    save(out / 'manifest.json', {'status': 'PASS', 'clinical_quality': 'NOT_EVALUATED',
         'baseline_commit': BASELINE, 'policy': check,
         'validation_report': str(a.validation.resolve()), 'validation_sha256': sha(validation_bytes),
         'candidates': candidates})


if __name__ == '__main__':
    main()
