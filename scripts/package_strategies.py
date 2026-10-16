"""Three reproducible v3.5-derived ZIPs; exclusive creation, no original writes."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = '81714d340207a8e5ca9886dd2129cbd6b9cc61f2'
NEW = ['app/nova_agent/strategies.py', 'app/nova_agent/strategy_config.py']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source(name):
    return subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=ROOT)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--report-dir', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE, 'app'], cwd=ROOT).decode().splitlines()
    paths = sorted(set(original + NEW))
    assert len(paths) == 26
    # No selection via recursive glob: secrets, ledgers, logs, or development data cannot enter.
    unchanged = []
    for path in original:
        data = (ROOT / path).read_bytes()
        if path != 'app/nova_agent/loop.py':
            assert data == source(path), path
            unchanged.append(path)
    def config(data):
        return ast.dump(next(n for n in ast.parse(data).body if isinstance(n, ast.ClassDef) and n.name == 'Config'))
    assert config((ROOT/'app/nova_agent/loop.py').read_bytes()) == config(source('app/nova_agent/loop.py'))
    manifests = []
    for strategy, label in [('A', 'differential'), ('B', 'clinical_decision'), ('C', 'patient_centered')]:
        archive = args.output / f'nova_doctor_bm25_candidate_v3_7_{strategy}_{label}_20261016.zip'
        files = []
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for path in paths:
                name = PurePosixPath(path).relative_to('app').as_posix()
                data = (ROOT / path).read_bytes()
                if name == 'nova_agent/strategy_config.py':
                    data = data.replace(b"STRATEGY = 'baseline'", f"STRATEGY = '{strategy}'".encode())
                    assert f"STRATEGY = '{strategy}'".encode() in data
                if name.endswith('.py'):
                    compile(data, name, 'exec')
                info = zipfile.ZipInfo(name, date_time=(2026, 10, 16, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                files.append({'path': name, 'bytes': len(data), 'sha256': digest(data)})
        smoke_dir = args.output.parent / ('smoke_' + strategy)
        smoke_dir.mkdir(exist_ok=False)
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            assert len(names) == len(set(names)) <= 5000
            assert {'run.py', 'requirements.txt', 'nova_sdk.py'}.issubset(names)
            assert not any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n or ':' in n for n in names)
            assert z.testzip() is None
            expanded = sum(i.file_size for i in z.infolist())
            assert archive.stat().st_size < 45_000_000
            assert expanded <= 500_000_000
            for row in files:
                data = z.read(row['path'])
                assert digest(data) == row['sha256']
                # Smoke executes ZIP code/assets; indexes already CRC/hash verified, not duplicated.
                if not row['path'].startswith('indexes/'):
                    target = smoke_dir / row['path']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as stream:
                        stream.write(data)
        subprocess.run([sys.executable, '-X', 'utf8', '-B', '-I', str(ROOT/'scripts/check_strategies_offline.py'),
                        '--smoke-app', str(smoke_dir.resolve()), '--strategy', strategy,
                        '--report', str((args.report_dir / f'smoke_{strategy}.json').resolve())], check=True, cwd=ROOT)
        with archive.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest = {'strategy': strategy, 'label': label, 'base_commit': BASE,
                    'filename': archive.name, 'bytes': archive.stat().st_size, 'sha256': sha,
                    'files': files, 'file_count': len(files), 'expanded_bytes': expanded,
                    'limit_bytes_exclusive': 45_000_000, 'crc_and_file_hashes_verified': True,
                    'baseline_unchanged_files': unchanged, 'config_class_unchanged': True,
                    'only_package_override': 'nova_agent/strategy_config.py',
                    'zip_code_entrypoint_mock_verified': True, 'real_model_evaluation': False}
        manifests.append(manifest)
        with archive.with_suffix('.zip.sha256').open('x', encoding='utf-8', newline='\n') as out:
            out.write(sha + '  ' + archive.name + '\n')
        print(json.dumps({k: manifest[k] for k in ('strategy', 'filename', 'bytes', 'sha256')}))
    # Candidate payloads differ only in the pinned selection, ensuring independent ablation.
    for row_index in range(len(manifests[0]['files'])):
        rows = [m['files'][row_index] for m in manifests]
        if rows[0]['path'] != 'nova_agent/strategy_config.py':
            assert len({r['sha256'] for r in rows}) == 1
    with (args.report_dir / 'candidate_manifests.json').open('x', encoding='utf-8', newline='\n') as out:
        json.dump(manifests, out, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
