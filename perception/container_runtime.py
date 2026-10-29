"""Execute reviewed argv inside a disposable, permission-scoped Linux container."""
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from perception.redactor import redact_secrets
from shared.schemas import ActionRequest, ActionResult

OUTPUT_LIMIT = 32_768


def _run(argv, timeout=5):
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=timeout, text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def availability() -> tuple[bool, str | None]:
    from backend.config import settings
    docker = shutil.which('docker')
    if not docker:
        return False, 'COMMAND_ISOLATION_UNAVAILABLE'
    try:
        result = _run([docker, 'image', 'inspect', '--format', '{{.Os}}', settings.SANDBOX_IMAGE])
        if result.returncode or result.stdout.strip() != 'linux':
            return False, 'SANDBOX_IMAGE_UNAVAILABLE'
        return True, None
    except (OSError, subprocess.SubprocessError):
        return False, 'COMMAND_ISOLATION_UNAVAILABLE'


def create_argv(req: ActionRequest, root: Path, name: str, network_name: str = 'prism-actions') -> list[str]:
    from backend.config import settings
    root = root.resolve(strict=True)
    relative = Path(req.working_dir).resolve(strict=True).relative_to(root)
    if any(character in str(root) for character in ',\r\n'):
        raise ValueError('Unsupported characters in sandbox root')
    user = f'{os.getuid()}:{os.getgid()}' if hasattr(os, 'getuid') else '65534:65534'
    # No host environment, Docker socket, devices, credentials, or other roots
    # are forwarded. Every runtime option precedes the trusted image name.
    return [shutil.which('docker') or 'docker', 'create', '--pull', 'never', '--name', name,
            '--network', network_name if req.access.network else 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges=true', '--pids-limit', '128',
            '--memory', '512m', '--cpus', '1', '--user', user,
            '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=67108864',
            '--mount', f'type=bind,src={root},dst=/workspace' + ('' if req.access.modify_files else ',readonly'),
            '--workdir', '/workspace' + (('/' + relative.as_posix()) if relative.parts else ''),
            '--env', 'HOME=/tmp', '--env', 'PYTHONDONTWRITEBYTECODE=1',
            '--env', 'PYTHONUNBUFFERED=1', '--log-driver', 'none',
            '--env', 'PYTHONPATH=/workspace/.prism/python:/workspace',
            '--env', 'PIP_TARGET=/workspace/.prism/python',
            '--env', 'PIP_CACHE_DIR=/tmp/pip-cache',
            '--env', 'npm_config_cache=/tmp/npm-cache',
            '--entrypoint', req.command[0], settings.SANDBOX_IMAGE, *req.command[1:]]


def execute(req: ActionRequest, root: Path, cancel_event: threading.Event | None = None) -> ActionResult:
    from backend.config import settings
    started = time.monotonic()
    name = 'prism-' + uuid.uuid4().hex
    docker = shutil.which('docker') or 'docker'
    output = [bytearray(), bytearray()]
    truncated = [False, False]
    proc = None
    readers = []
    network_name = name + '-network'
    network_created = False

    def result(status, code=None, reason=None, error=''):
        text = [redact_secrets(bytes(buffer).decode('utf-8', errors='replace')) for buffer in output]
        for index in range(2):
            if truncated[index]:
                text[index] += '\n[OUTPUT_TRUNCATED]'
        return ActionResult(action_id=req.action_id, status=status, exit_code=code,
                            stdout=text[0], stderr=text[1] + error,
                            denial_reason=reason, duration_ms=int((time.monotonic() - started)*1000))

    def consume(stream, index):
        try:
            while chunk := stream.read(4096):
                remaining = OUTPUT_LIMIT - len(output[index])
                output[index].extend(chunk[:max(0, remaining)])
                if len(chunk) > remaining:
                    truncated[index] = True
        finally:
            stream.close()

    try:
        if cancel_event and cancel_event.is_set():
            return result('denied', reason='ACTION_CANCELLED')
        from shared.paths import safe_workspace
        safe_workspace(root, check_files=True)
        if req.access.network:
            network = _run([docker, 'network', 'create', '--driver', 'bridge', '--label', 'prism.action=true', network_name], timeout=15)
            if network.returncode:
                return result('failed', error='Unable to create a private action network.')
            network_created = True
        created = _run(create_argv(req, root, name, network_name), timeout=15)
        if created.returncode:
            return result('failed', code=created.returncode, error='Unable to create isolated action container.')
        if cancel_event and cancel_event.is_set():
            return result('denied', reason='ACTION_CANCELLED')
        proc = subprocess.Popen([docker, 'start', '--attach', name], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for index, stream in enumerate([proc.stdout, proc.stderr]):
            thread = threading.Thread(target=consume, args=(stream, index), daemon=True)
            thread.start()
            readers.append(thread)
        interrupted = None
        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                interrupted = 'cancelled'
                break
            if time.monotonic() - started >= settings.ACTION_TIMEOUT_SECONDS:
                interrupted = 'timeout'
                break
            time.sleep(0.05)
        if interrupted:
            # Removing the container stops its complete process tree, not just
            # the attached Docker client. No unreviewed host command runs.
            _run([docker, 'rm', '--force', name])
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for thread in readers:
            thread.join(timeout=2)
        if interrupted == 'timeout':
            return result('timeout', reason='ACTION_TIMEOUT')
        if interrupted == 'cancelled':
            return result('denied', reason='ACTION_CANCELLED')
        # docker start --attach does not reliably convey the container's exit
        # code on every supported CLI version; inspect the actual process.
        inspected = _run([docker, 'inspect', '--format', '{{.State.ExitCode}}', name])
        code = int(inspected.stdout.strip()) if inspected.returncode == 0 else 125
        return result('ok' if code == 0 else 'failed', code=code)
    except (OSError, ValueError, subprocess.SubprocessError):
        return result('failed', error='Isolated execution failed; check Docker and the sandbox image.')
    finally:
        try:
            _run([docker, 'rm', '--force', name])
        except (OSError, subprocess.SubprocessError):
            pass
        if network_created:
            try:
                _run([docker, 'network', 'rm', network_name])
            except (OSError, subprocess.SubprocessError):
                pass
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
