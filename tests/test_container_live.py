"""Real OS boundary checks. CI builds the image and explicitly enables these."""
import os
import threading
import time
from pathlib import Path
import pytest
from backend.config import settings
from shared.approval import sign_action
from shared.schemas import ActionRequest, ExecutionAccess
from perception import sandbox
from perception.container_runtime import availability

pytestmark = pytest.mark.skipif(os.getenv('PRISM_RUN_DOCKER_TESTS') != '1', reason='Requires Docker and the built sandbox image')


@pytest.fixture(autouse=True)
def live(monkeypatch):
    assert availability()[0], 'Build prism-sandbox:local and start Docker before running these checks'


def execute_script(root, text, cancel_event=None, write=True, network=False):
    (root / 'probe.py').write_text(text, encoding='utf-8')
    command = ['python', 'probe.py']
    req = ActionRequest(action_id='probe', kind='run_command', command=command,
                        working_dir=str(root), approval_token='', access=ExecutionAccess(modify_files=write, network=network))
    req.approval_token = sign_action(req, 'test-secret')
    return sandbox.execute(req, secret='test-secret', allowed_root=str(root), cancel_event=cancel_event)


def test_real_command_and_workspace_write(tmp_path):
    result = execute_script(tmp_path, "from pathlib import Path\nPath('result.txt').write_text('approved')\nprint('done')\n")
    assert result.status == 'ok', result
    assert (tmp_path / 'result.txt').read_text() == 'approved'
    assert 'done' in result.stdout


def test_network_and_host_filesystem_are_unreachable(tmp_path):
    outside = tmp_path.parent / 'host-only-secret.txt'
    outside.write_text('host-only')
    script = """from pathlib import Path
import socket
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
    raise AssertionError('network escaped')
except OSError:
    pass
assert not Path('/var/run/docker.sock').exists()
assert not Path('../host-only-secret.txt').exists()
try:
    Path('/outside.txt').write_text('escaped')
    raise AssertionError('root filesystem writable')
except OSError:
    pass
print('boundaries enforced')
"""
    result = execute_script(tmp_path, script)
    assert result.status == 'ok', result
    assert 'boundaries enforced' in result.stdout
    assert outside.read_text() == 'host-only'


def test_backend_credentials_are_not_inherited(tmp_path, monkeypatch):
    monkeypatch.setenv('NVIDIA_API_KEY', 'nvapi-private-host-value')
    result = execute_script(tmp_path, "import os\nassert 'NVIDIA_API_KEY' not in os.environ\nassert 'APPROVAL_SECRET' not in os.environ\n")
    assert result.status == 'ok', result


def test_output_is_bounded_and_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv('PRISM_SECRET', 'super-test-secret')
    result = execute_script(tmp_path, "print('super-test-secret')\nprint('x' * 200000)\n")
    assert result.status == 'ok' and len(result.stdout) < 33_000
    assert 'super-test-secret' not in result.stdout and 'OUTPUT_TRUNCATED' in result.stdout


def test_timeout_stops_child_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'ACTION_TIMEOUT_SECONDS', 2)
    script = "import subprocess, time\nsubprocess.Popen(['python', '-c', \"import time; from pathlib import Path; time.sleep(5); Path('escaped.txt').touch()\"])\ntime.sleep(10)\n"
    assert execute_script(tmp_path, script).status == 'timeout'
    time.sleep(5)
    assert not (tmp_path / 'escaped.txt').exists()


def test_cancellation_stops_container(tmp_path):
    event = threading.Event()
    timer = threading.Timer(1, event.set)
    timer.start()
    try:
        result = execute_script(tmp_path, "import time\ntime.sleep(10)\n", event)
        assert result.denial_reason == 'ACTION_CANCELLED'
    finally:
        timer.cancel()


def test_readonly_workspace_is_enforced(tmp_path):
    result = execute_script(tmp_path, "from pathlib import Path\nPath('blocked.txt').write_text('no')\n", write=False)
    assert result.status == 'failed' and not (tmp_path / 'blocked.txt').exists()


def test_granted_network_has_a_route(tmp_path):
    result = execute_script(tmp_path, "from pathlib import Path\nassert '00000000' in Path('/proc/net/route').read_text()\nprint('network granted')\n", write=False, network=True)
    assert result.status == 'ok', result


def test_patched_node_and_npm_bundle_is_usable(tmp_path):
    for command, expected in [(['npm','--version'],'12.2.1'),
        (['node','-e',"console.log(require('/usr/local/lib/node_modules/npm/node_modules/undici/package.json').version)"],'6.29.1')]:
        req = ActionRequest(action_id='patched-node',kind='run_command',command=command,
                            working_dir=str(tmp_path),approval_token='')
        req.approval_token = sign_action(req,'test-secret')
        result = sandbox.execute(req,secret='test-secret',allowed_root=str(tmp_path))
        assert result.status == 'ok' and expected in result.stdout, result


def test_dependency_install_requires_grant_then_installs_local_wheel(tmp_path):
    import zipfile
    wheel=tmp_path/'prism_probe-1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel,'w') as archive:
        archive.writestr('prism_probe.py','value = 42\n')
        archive.writestr('prism_probe-1.0.dist-info/METADATA','Metadata-Version: 2.1\nName: prism-probe\nVersion: 1.0\n')
        archive.writestr('prism_probe-1.0.dist-info/WHEEL','Wheel-Version: 1.0\nGenerator: prism-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('prism_probe-1.0.dist-info/RECORD','')
    req=ActionRequest(action_id='install',kind='run_command',command=['python','-m','pip','install','--no-index','--no-deps',wheel.name],working_dir=str(tmp_path),approval_token='')
    req.approval_token=sign_action(req,'test-secret')
    assert sandbox.execute(req,secret='test-secret',allowed_root=str(tmp_path)).denial_reason=='EXECUTION_ACCESS_REQUIRED'
    assert not (tmp_path/'.prism/python/prism_probe.py').exists()
    req.access=ExecutionAccess(modify_files=True,install_dependencies=True,network=True)
    req.approval_token=sign_action(req,'test-secret')
    result=sandbox.execute(req,secret='test-secret',allowed_root=str(tmp_path))
    assert result.status=='ok', result
    assert (tmp_path/'.prism/python/prism_probe.py').is_file()
