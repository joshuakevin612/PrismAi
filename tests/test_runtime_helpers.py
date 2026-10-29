import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from backend.config import settings
from backend.workspace_context import read_workspace_files
from perception.artifacts import ScreenshotStore
from perception.container_runtime import create_argv
from shared.schemas import ActionRequest, ContextBundle, TerminalError
from backend.workspace_context import materialize_edit
from backend.model_client import FileEditFromModel
from perception.patching import apply_verified_diff
import pytest


def test_container_command_has_no_host_secrets_or_network(tmp_path):
    request = ActionRequest(action_id='x', kind='run_command', command=['python', 'test.py'], working_dir=str(tmp_path), approval_token='')
    argv = create_argv(request, tmp_path, 'prism-test')
    assert argv[argv.index('--network') + 1] == 'none'
    assert '--read-only' in argv and '--cap-drop' in argv
    assert 'no-new-privileges=true' in argv
    assert not any('NVIDIA_API_KEY' in part or 'docker.sock' in part for part in argv)
    assert argv[-2:] == [settings.SANDBOX_IMAGE, 'test.py']


def test_screenshot_expiry_deletes_only_owned_files():
    store = ScreenshotStore()
    path = store.allocate()
    path.write_bytes(b'png')
    unknown = path.parent / 'unrelated.txt'
    unknown.write_text('preserve')
    store.cleanup(ttl=0)
    assert not path.exists() and unknown.exists()
    store.cleanup(close=True)
    assert unknown.exists()
    unknown.unlink()
    path.parent.rmdir()


def test_source_context_stays_inside_root_and_redacts(tmp_path):
    (tmp_path / 'app.py').write_text('password=supersecret123\n')
    errors = [TerminalError(message='failure', file='app.py', raw_excerpt=''),
              TerminalError(message='failure', file='../outside.py', raw_excerpt='')]
    bundle = ContextBundle(collected_at=datetime.now(timezone.utc), terminal_errors=errors)
    files = read_workspace_files(bundle, str(tmp_path))
    assert set(files) == {'app.py'} and 'supersecret123' not in files['app.py']


@pytest.mark.parametrize('original,replacement', [('before\n','after\n'), ('before','after')])
def test_model_replacements_produce_exact_applicable_diffs(tmp_path, original, replacement):
    path = tmp_path / 'app.py'
    path.write_text(original)
    edit = FileEditFromModel(path='app.py', old_text=original, new_text=replacement)
    patch = materialize_edit(edit, str(tmp_path))
    assert path.read_text() == original
    apply_verified_diff(path, patch.unified_diff)
    assert path.read_text() == replacement


def test_model_replacement_cannot_guess_or_escape(tmp_path):
    (tmp_path / 'app.py').write_text('duplicate duplicate')
    for path, old in [('app.py','duplicate'), ('app.py','missing'), ('../outside.py',''), ('.env','')]:
        with pytest.raises(ValueError):
            materialize_edit(FileEditFromModel(path=path,old_text=old,new_text='replacement'), str(tmp_path))


def test_v2_token_binds_directory_and_access(tmp_path):
    from shared.approval import sign_action, verify_action
    from shared.schemas import ActionRequest, ExecutionAccess
    req=ActionRequest(action_id='a',kind='run_command',command=['python','test.py'],working_dir=str(tmp_path),approval_token='')
    req.approval_token=sign_action(req,'secret')
    assert verify_action(req,'secret')
    assert not verify_action(req.model_copy(update={'working_dir':str(tmp_path.parent)}),'secret')
    assert not verify_action(req.model_copy(update={'access':ExecutionAccess(network=True)}),'secret')


def test_container_access_changes_only_explicit_mount_and_network(tmp_path):
    from shared.schemas import ExecutionAccess
    req=ActionRequest(action_id='a',kind='run_command',command=['python','probe.py'],working_dir=str(tmp_path),approval_token='')
    readonly=create_argv(req,tmp_path,'a')
    assert readonly[readonly.index('--mount')+1].endswith(',readonly')
    req.access=ExecutionAccess(modify_files=True,network=True)
    granted=create_argv(req,tmp_path,'a')
    assert not granted[granted.index('--mount')+1].endswith(',readonly')
    assert granted[granted.index('--network')+1]=='prism-actions'
