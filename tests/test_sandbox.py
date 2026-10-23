"""
tests/test_sandbox.py
Tests successful sandbox execution of allowlisted commands and patch application.
"""

import os
from pathlib import Path
import pytest

from shared.schemas import ActionRequest, PatchFile
from perception.sandbox import (
    execute,
    validate_action,
    generate_approval_token,
    ENV_ALLOWED_ROOT,
    ENV_APPROVAL_SECRET,
)


@pytest.fixture(autouse=True)
def setup_sandbox_env(tmp_path):
    os.environ[ENV_ALLOWED_ROOT] = str(tmp_path)
    os.environ[ENV_APPROVAL_SECRET] = "secure-test-secret"
    yield tmp_path


def test_sandbox_run_command_success(tmp_path):
    action_id = "act_cmd_valid"
    cmd = ["python", "-c", "print('sandbox_test_ok')"]
    token = generate_approval_token(
        action_id=action_id,
        kind="run_command",
        command=cmd,
        secret="secure-test-secret",
    )

    req = ActionRequest(
        action_id=action_id,
        kind="run_command",
        command=cmd,
        working_dir=str(tmp_path),
        approval_token=token,
    )

    policy_ok, reason = validate_action(req)
    assert policy_ok
    assert reason is None

    res = execute(req)
    assert res.status == "ok"
    assert res.exit_code == 0
    assert "sandbox_test_ok" in res.stdout
    assert res.duration_ms >= 0


def test_sandbox_apply_patch_success(tmp_path):
    # Setup test file in tmp_path
    target_file = tmp_path / "hello.py"
    target_file.write_text("def hello():\n    return 'old'\n", encoding="utf-8")

    diff = """--- a/hello.py
+++ b/hello.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'old'
+    return 'new'"""

    patch = PatchFile(path="hello.py", unified_diff=diff)
    action_id = "act_patch_valid"
    token = generate_approval_token(
        action_id=action_id,
        kind="apply_patch",
        patch=patch,
        secret="secure-test-secret",
    )

    req = ActionRequest(
        action_id=action_id,
        kind="apply_patch",
        patch=patch,
        working_dir=str(tmp_path),
        approval_token=token,
    )

    policy_ok, reason = validate_action(req)
    assert policy_ok
    assert reason is None

    res = execute(req)
    assert res.status == "ok"
    assert res.exit_code == 0

    # Verify file was modified
    new_text = target_file.read_text(encoding="utf-8")
    assert "return 'new'" in new_text
    assert "return 'old'" not in new_text
