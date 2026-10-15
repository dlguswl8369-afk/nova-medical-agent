"""Container-only supervisor reusing preserved v3.2 limits/entry/export tools."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
sys.path.insert(0,'/tools')
from limits import measure
from artifacts import emit


def main():
    out=Path('/output');start=time.monotonic()
    summary={'status':'RUNNING','real_api_calls':0,'limits_before':measure(),'uid':os.getuid(),'scenarios':[]}
    def run(name,cmd,timeout,env=None):
        p=subprocess.run(cmd,capture_output=True,timeout=timeout,env=env)
        (out/(name+'.stdout')).write_bytes(p.stdout);(out/(name+'.stderr')).write_bytes(p.stderr)
        if p.returncode:raise RuntimeError(name+'_FAILED')
        return p
    try:
        assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and os.getuid()==65532
        mounts=[line.split() for line in Path('/proc/mounts').read_text().splitlines()]
        assert any(r[1]=='/' and 'ro' in r[3].split(',') for r in mounts)
        summary['root_readonly']=True
        network=run('network',[sys.executable,'-B','/tools/network_probe.py'],20)
        summary['network']=json.loads(network.stdout)
        runtime=run('runtime',[sys.executable,'-B','-I','/fixtures/scripts/probe_guidelines_runtime.py'],600)
        summary['runtime']=json.loads(runtime.stdout)
        for scenario in ('normal','recovery','uncertain'):
            p=run(scenario,[sys.executable,'-B','/tools/entry_probe.py','--app','/app','--fixtures','/fixtures',
                           '--manifest','/manifest/candidate_manifest.json','--scenario',scenario],2405)
            summary['scenarios'].append(json.loads(p.stdout))
        scratch=Path('/tmp/verify');scratch.mkdir()
        for folder in ('tests','scripts','dev'):shutil.copytree(Path('/fixtures')/folder,scratch/folder)
        (scratch/'app').symlink_to('/app',target_is_directory=True)
        env=dict(os.environ,NOVA_RAG_SOURCES='legacy')
        proc=run('regression',[sys.executable,'-B','-I',str(scratch/'scripts/run_v3_tests.py')],1800,env)
        last=json.loads(proc.stdout.decode().strip().splitlines()[-1])
        summary['regression']=json.loads(Path(last['report']).read_text())
        assert summary['regression']['tests']==145 and summary['regression']['passed']
        run('extension',[sys.executable,'-B','-I',str(scratch/'tests/test_extension.py')],300,env)
        summary['extension_tests']=13
        shutil.copytree(scratch/'reports',out/'suite_reports')
        summary['status']='PASS_LINUX_EXTENSION'
    except Exception as exc:
        summary.update(status='FAILED',error=str(exc))
        raise
    finally:
        summary.update(limits_after=measure(),elapsed_seconds=time.monotonic()-start)
        (out/'extension_result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__':
    try:main()
    finally:emit('/output')
