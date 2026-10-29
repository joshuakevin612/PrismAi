"""tests/test_security_and_sandbox.py - Tests security, HMAC tokens, and sandbox policy validation."""

import pytest
from backend.security import generate_approval_token, verify_approval_token
from perception.sandbox import ActionRequest, execute, validate_action
from shared.schemas import PatchFile

SECRET = "super-secret-key-12345"


def test_hmac_token_verification_success():
    patch = PatchFile(path="app.py", unified_diff="--- a\n+++ b\n")
    token = generate_approval_token("act-1", secret=SECRET, patch=patch)

    assert verify_approval_token(token, "act-1", secret=SECRET, patch=patch) is True


def test_hmac_token_rejection_on_tamper():
    patch = PatchFile(path="app.py", unified_diff="--- a\n+++ b\n")
    token = generate_approval_token("act-1", secret=SECRET, patch=patch)

    # Tampered path
    tampered_patch = PatchFile(path="other.py", unified_diff="--- a\n+++ b\n")
    assert verify_approval_token(token, "act-1", secret=SECRET, patch=tampered_patch) is False

    # Tampered action_id
    assert verify_approval_token(token, "act-2", secret=SECRET, patch=patch) is False

    # Tampered secret
    assert verify_approval_token(token, "act-1", secret="wrong-secret", patch=patch) is False


def test_sandbox_validate_action_allowlist(monkeypatch, tmp_path):
    from perception import container_runtime
    monkeypatch.setattr(container_runtime, "availability", lambda: (True, None))
    # Allowlisted command
    req = ActionRequest(
        action_id="a1",
        kind="run_command",
        command=["pytest", "tests/test_main.py"],
        working_dir=str(tmp_path),
        approval_token="dummy",
    )
    ok, reason = validate_action(req, allowed_root=str(tmp_path))
    assert ok is True
    assert reason is None

    # Forbidden command (rm)
    req_rm = ActionRequest(
        action_id="a2",
        kind="run_command",
        command=["rm", "-rf", "/tmp"],
        working_dir=".",
        approval_token="dummy",
    )
    ok, reason = validate_action(req_rm, allowed_root=".")
    assert ok is False
    assert "COMMAND_FORBIDDEN" in (reason or "")


def test_sandbox_validate_action_path_traversal():
    # Path escaping allowed_root
    patch = PatchFile(path="../../etc/passwd", unified_diff="...")
    req = ActionRequest(
        action_id="a3",
        kind="apply_patch",
        patch=patch,
        working_dir=".",
        approval_token="dummy",
    )
    ok, reason = validate_action(req, allowed_root=".")
    assert ok is False
    assert "PATCH_OUTSIDE_ALLOWED_ROOT" in (reason or "")


def test_sandbox_execute_requires_valid_approval_token():
    cmd = ["pytest", "tests/"]
    valid_token = generate_approval_token("act-exec-1", secret=SECRET, command=cmd)

    # Missing / invalid token
    invalid_req = ActionRequest(
        action_id="act-exec-1",
        kind="run_command",
        command=cmd,
        working_dir=".",
        approval_token="forged-token",
    )
    result = execute(invalid_req, secret=SECRET, allowed_root=".")
    assert result.status == "denied"
    assert result.denial_reason == "INVALID_OR_MISSING_APPROVAL_TOKEN"
