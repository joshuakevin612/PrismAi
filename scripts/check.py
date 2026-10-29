"""The same release verification command locally and in CI; no live context."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def run(argv, **kwargs):
    print('Check:', ' '.join(map(str,argv)),flush=True)
    subprocess.run(list(map(str,argv)),cwd=ROOT,check=True,**kwargs)


def contract_smoke(python=sys.executable, root=ROOT, config=None):
    """Start a new process, no model credentials or workstation context."""
    with tempfile.TemporaryDirectory(prefix='prism-contract-') as folder:
        temp = Path(folder)
        (temp/'workspace').mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            port = listener.getsockname()[1]
        token = secrets.token_urlsafe(48)
        env = {**os.environ,'API_SESSION_TOKEN':token,'PORT':str(port),'HOST':'127.0.0.1',
            'DEV_FRONTEND':'false','NVIDIA_API_KEY':'','GITHUB_TOKEN':'',
            'ALLOWED_ROOT':str(temp/'workspace'),'STATE_DIR':str(temp/'state'),
            'API_BASE_URL':f'http://127.0.0.1:{port}/api'}
        if config:
            env['PRISM_ENV_FILE'] = str(config)
        with (temp/'server.log').open('w+',encoding='utf-8') as log:
            process = subprocess.Popen([str(python),str(root/'scripts/run_backend.py'),'--no-browser'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError('Isolated backend stopped before becoming ready')
                    try:
                        request = urllib.request.Request(env['API_BASE_URL']+'/access',headers={'Authorization':'Bearer '+token})
                        with opener.open(request,timeout=1):
                            break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError('Isolated backend startup timed out')
                # Check the production HTML and the unauthenticated boundary.
                with opener.open(urllib.request.Request(env['API_BASE_URL'].removesuffix('/api')+'/',headers={'Authorization':'Bearer '+token}),timeout=5) as response:
                    if '<div id="root"></div>' not in response.read().decode():
                        raise RuntimeError('Production frontend was not served')
                run([shutil.which('npm') or 'npm','run','test:integration','--prefix','frontend'],env=env)
            except Exception:
                log.flush()
                log.seek(0)
                # Never print the per-session token even if a dependency logs it.
                print(log.read().replace(token,'[REDACTED_SESSION]'),file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker',action='store_true')
    parser.add_argument('--ocr',action='store_true')
    parser.add_argument('--security',action='store_true')
    parser.add_argument('--tools-python',default=sys.executable)
    args = parser.parse_args()
    tools = args.tools_python
    env = {**os.environ,'PRISM_RUN_DOCKER_TESTS':'1' if args.docker else '0',
           'PRISM_RUN_OCR_TESTS':'1' if args.ocr else '0'}
    run([tools,'-m','ruff','check','backend','perception','shared','scripts','tests'])
    run([sys.executable,'scripts/check_secrets.py'])
    run([sys.executable,'-m','pip','check'])
    run([sys.executable,'-m','pytest','-q'],env=env)
    npm = shutil.which('npm') or 'npm'
    run([npm,'test','--prefix','frontend'])
    run([npm,'run','build','--prefix','frontend'])
    from backend.main import app
    for name in ['openapi.json','fixtures/openapi.json']:
        if json.loads((ROOT/name).read_text()) != app.openapi():
            raise RuntimeError('Regenerate contract snapshots: python scripts/sync-backend-contract.py')
    run([tools,'-c',"import pathlib,yaml; [yaml.safe_load(p.read_text()) for p in pathlib.Path('.github').rglob('*.yml')]"])
    contract_smoke()
    run([sys.executable,'scripts/notices.py'])
    if args.security:
        run([npm,'audit','--prefix','frontend','--audit-level=high'])
        run([tools,'-m','pip_audit','--path',sysconfig.get_path('purelib'),'--progress-spinner','off'])
    print('Release checks passed.',flush=True)


if __name__ == '__main__':
    main()
