"""Package pinned v3.5-derived candidates; exercise extracted run.py without network."""
import argparse
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
from check_batch import ROOT, BASELINE, APP_CHANGES, git, load_harness, policy

NAMES = {'V0': 'baseline', 'V1': 'clinical_rag', 'V2': 'clinical_interview',
         'V3': 'communication', 'V4': 'integrated'}
BASE_ZIP = ROOT.parent / 'nova_v35_simple_20261016/deliverables/nova_doctor_bm25_candidate_v3_5_simple_20261016.zip'
BASE_HASH = '31648ae7be3285c08f1103b9e7c741ba1b9af5e32f757b54cb91aebb2ea5faf7'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def smoke(a, h):
    app = a.app.resolve()
    os.environ['NOVA_TEST_APP'] = str(app)
    os.environ['NOVA_RAG_SOURCES'] = 'legacy'
    sys.path[:0] = [str(app), str(ROOT / 'tests')]
    sys.addaudithook(lambda event, args: h.guard_event(event, args, a.output.resolve()))
    import nova_agent
    import nova_sdk
    from test_agent import MockClient, plan
    from test_simple_v35 import Replies, say
    assert Path(nova_agent.__file__).resolve().is_relative_to(app)
    assert Path(nova_sdk.__file__).resolve().is_relative_to(app)
    c = Replies([say('복용약과 알레르기가 있나요?'), {'action': 'EXAM', 'content': '복부 압통 확인'},
                 say('추가 평가가 필요해요', 'EXPLAIN'), {'action': 'DONE'}, plan()],
                ['약은 먹어요. 이름은 몰라요.', '무슨 뜻인가요?'])
    captured = []
    original = nova_agent.prepare
    def prepare():
        state = original(); captured.append(state); return state
    with patch.object(nova_sdk, 'Client', return_value=c), patch.object(nova_agent, 'prepare', side_effect=prepare):
        runpy.run_path(str(app / 'run.py'), run_name='__main__')
    report = captured[0].report
    assert report['termination_reason'] == 'DOCTOR_DONE'
    assert report['record_outcome'] == 'DOCTOR_RECORD_VALIDATED'
    assert report['invalid_model_outputs'] == 0 and c.chat_number == 5
    assert report['actions_succeeded'] == 3 and report['acknowledged_explanations'] == 1
    assert not report['patient_understanding_assessed']
    assert report.get('strategy', 'V0') == a.smoke
    contexts = [json.loads(m[1]['content']) for m in c.prompts]
    assert isinstance(contexts[-1]['current_patient_observations'], list)
    assert isinstance(contexts[0]['current_patient_observations'], dict) == (a.smoke in ('V2', 'V3', 'V4'))
    note = c.submissions[0]['note']
    assert '약은 먹어요. 이름은 몰라요.' in note['S']['hpi']
    assert note['O']['exam'].count('[F1]') == 1 and '[F3]' in note['O']['exam']
    assert note['O']['tests'] == '' and '[실제 SAY 설명]' in note['P']['education']
    assert '무슨 뜻인가요?' in json.dumps(note, ensure_ascii=False)
    assert not any(call['action'] == 'TEST' for call in c.calls)
    result = {'status': 'PASS', 'strategy': a.smoke, 'entrypoint': 'extracted run.py',
              'sdk': 'extracted unmodified SDK; transport mocked', 'network_process_guard': 'pinned harness audit hook',
              'doctor_calls': c.chat_number, 'real_api_calls': 0, 'model': report['model'],
              'termination': report['termination_reason'], 'record': report['record_outcome'],
              'action_observation_representation': type(contexts[0]['current_patient_observations']).__name__,
              'step_sha256': sha(c.prompts[0][0]['content'].encode()),
              'record_prompt_sha256': sha(c.prompts[-1][0]['content'].encode()),
              'record_context_sha256': sha(c.prompts[-1][1]['content'].encode()),
              'note_sha256': sha(json.dumps(note, ensure_ascii=False, sort_keys=True).encode()),
              'action_input_bytes': [len(m[0]['content'].encode()) + len(m[1]['content'].encode()) for m in c.prompts[:-1]],
              'packet_statuses': [p['status'] for p in report.get('experiment_packets', [])],
              'clinical_quality': 'NOT_EVALUATED', 'understanding': 'REVIEW'}
    save(a.output / 'smoke.json', result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--smoke', choices=NAMES)
    p.add_argument('--app', type=Path)
    a = p.parse_args()
    h = load_harness(ROOT.parent / 'nova-medical-agent-harness')
    if a.smoke:
        smoke(a, h); return
    check = policy(h)
    out = a.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    base_paths = git(ROOT, 'ls-tree', '-r', '--name-only', BASELINE, 'app/').decode().splitlines()
    base_names = {n[4:] for n in base_paths}
    assert sha(BASE_ZIP.read_bytes()) == BASE_HASH and BASE_ZIP.stat().st_size == 44989264
    with zipfile.ZipFile(BASE_ZIP) as z:
        assert set(z.namelist()) == base_names and z.testzip() is None
        for name in base_paths:
            assert z.read(name[4:]) == git(ROOT, 'show', BASELINE + ':' + name), name
    paths = sorted(set(base_paths) | APP_CHANGES)
    for name in base_paths:
        if name not in APP_CHANGES:
            assert (ROOT / name).read_bytes() == git(ROOT, 'show', BASELINE + ':' + name), name
    env = {k: v for k, v in os.environ.items() if not (k.startswith('NOVA_') or any(t in k.upper() for t in ('TOKEN', 'API_KEY', 'SECRET')))}
    candidates = []
    for version, label in NAMES.items():
        target = BASE_ZIP if version == 'V0' else out / f'nova_doctor_bm25_candidate_{version}_{label}_20261021.zip'
        if version != 'V0':
            with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for name in paths:
                    data = (ROOT / name).read_bytes()
                    if name.endswith('/experiment_config.py'):
                        data = data.replace(b"STRATEGY = 'V0'", f"STRATEGY = '{version}'".encode())
                    if name.endswith('.py'):
                        compile(data, name, 'exec')
                    info = zipfile.ZipInfo(name[4:], (2026, 10, 21, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
                    z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        assert target.stat().st_size < 45000000, 'CANDIDATE_EXCEEDS_45MB_TARGET'
        stage = out / version; stage.mkdir()
        file_rows = []
        with zipfile.ZipFile(target) as z:
            assert z.testzip() is None
            expected = base_names if version == 'V0' else {n[4:] for n in paths}
            assert len(z.namelist()) == len(expected) and set(z.namelist()) == expected
            assert {'run.py', 'requirements.txt'} <= expected
            assert sum(i.file_size for i in z.infolist()) < 500000000
            for name in z.namelist():
                dest = (stage / 'app' / name).resolve()
                assert dest.is_relative_to((stage / 'app').resolve())
                data = z.read(name)
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
                file_rows.append({'path': name, 'sha256': sha(data), 'bytes': len(data)})
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-I', __file__, '--smoke', version,
                                 '--app', str(stage / 'app'), '--output', str(stage)], env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=120)
        (stage / 'smoke.log').write_text(result.stderr, encoding='utf-8', newline='\n')
        if result.returncode:
            raise RuntimeError('EXTRACTED_ENTRYPOINT_FAILED: ' + version + '\n' + result.stderr[-3000:])
        for row in file_rows:
            assert sha((stage / 'app' / row['path']).read_bytes()) == row['sha256']
        candidates.append({'candidate': version + '_' + label, 'strategy': version, 'baseline': BASELINE,
                           'path': str(target), 'bytes': target.stat().st_size, 'sha256': sha(target.read_bytes()),
                           'reused': version == 'V0', 'changed_app_files': [] if version == 'V0' else sorted(APP_CHANGES),
                           'files': file_rows, 'smoke': json.loads((stage / 'smoke.json').read_text(encoding='utf-8'))})
        print(json.dumps({'candidate': version, 'bytes': target.stat().st_size, 'smoke': 'PASS'}), flush=True)
    assert len({c['smoke']['record_prompt_sha256'] for c in candidates}) == 1
    assert len({c['smoke']['record_context_sha256'] for c in candidates}) == 1
    assert len({c['smoke']['note_sha256'] for c in candidates}) == 1
    assert check['app_snapshot'] == h.changed_app(ROOT, 'v3.5')[2]
    save(out / 'manifest.json', {'status': 'PASS', 'clinical_quality': 'NOT_EVALUATED', 'candidates': candidates})


if __name__ == '__main__':
    main()
