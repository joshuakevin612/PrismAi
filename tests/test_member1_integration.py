"""Exercise M1 through M2's actual schemas, tokens and live-mode dispatch."""
import asyncio
import threading
import time
from unittest.mock import Mock

import pytest
import perception
from backend.config import settings
from backend.security import generate_approval_token
from perception import collector, sandbox
from shared.approval import sign_action
from shared.schemas import ExecutionAccess, ActionRequest, ContextRequest, GithubTarget, PatchFile


@pytest.fixture
def live(monkeypatch):
    # Host-independent policy tests; real container tests are separate.
    from perception import container_runtime
    monkeypatch.setattr(container_runtime, 'availability', lambda: (False, 'COMMAND_ISOLATION_UNAVAILABLE'))


def patch_request(root, diff=None, path="demo.txt"):
    patch = PatchFile(path=path, unified_diff=diff or "--- a/demo.txt\n+++ b/demo.txt\n@@ -1 +1 @@\n-before\n+after\n")
    req = ActionRequest(action_id="m1-patch", kind="apply_patch", patch=patch,
                         working_dir=str(root), approval_token="", access=ExecutionAccess(modify_files=True))
    req.approval_token = sign_action(req, "test-secret")
    return req


def test_live_patch_uses_backend_token_and_writes_file(live, tmp_path):
    target = tmp_path / "demo.txt"
    target.write_text("before\n")
    result = sandbox.execute(patch_request(tmp_path), secret="test-secret", allowed_root=str(tmp_path))
    assert result.status == "ok"
    assert target.read_text() == "after\n"


@pytest.mark.parametrize("token", ["", "forged"])
def test_live_patch_requires_token(live, tmp_path, token):
    req = patch_request(tmp_path)
    req.approval_token = token
    result = sandbox.execute(req, secret="test-secret", allowed_root=str(tmp_path))
    assert result.denial_reason == "INVALID_OR_MISSING_APPROVAL_TOKEN"
    assert not (tmp_path / "demo.txt").exists()


def test_stale_patch_does_not_modify_file(live, tmp_path):
    target = tmp_path / "demo.txt"
    target.write_text("changed since review\n")
    result = sandbox.execute(patch_request(tmp_path), secret="test-secret", allowed_root=str(tmp_path))
    assert result.status == "denied" and result.denial_reason == 'PATCH_INVALID_OR_STALE'
    assert target.read_text() == "changed since review\n"


@pytest.mark.parametrize("path", ["../outside.txt", ".env", ".git/config"])
def test_live_patch_denies_escape_and_protected_paths(live, tmp_path, path):
    ok, reason = sandbox.validate_action(patch_request(tmp_path, path=path), allowed_root=str(tmp_path))
    assert not ok


@pytest.mark.parametrize("argv,reason", [
    (["rm", "-rf", "/"], "COMMAND_FORBIDDEN"),
    (["curl", "https://example.com"], "COMMAND_FORBIDDEN"),
    (["python", "-c", "print(1);print(2)"], "SHELL_METACHARACTERS_DETECTED"),
    (["python", "-c", "open('../outside', 'w')"], "COMMAND_ISOLATION_UNAVAILABLE"),
    (["node", "network.js"], "COMMAND_ISOLATION_UNAVAILABLE"),
    (["git", "fetch"], "COMMAND_ISOLATION_UNAVAILABLE"),
])
def test_live_commands_cannot_bypass_isolation(live, tmp_path, argv, reason):
    req = ActionRequest(action_id="command", kind="run_command", command=argv,
                        working_dir=str(tmp_path), approval_token=generate_approval_token("command", secret="test-secret", command=argv))
    req.access = ExecutionAccess(modify_files=True, install_dependencies=True, network=True)
    req.approval_token = sign_action(req, "test-secret")
    assert reason in sandbox.validate_action(req, allowed_root=str(tmp_path))[1]
    result = sandbox.execute(req, secret="test-secret", allowed_root=str(tmp_path))
    assert result.status == "denied" and reason in result.denial_reason


def test_collector_shared_deadline_keeps_partial_results(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(collector, "TOTAL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(collector, "capture_screen", lambda: (release.wait(2), []))
    monkeypatch.setattr(collector, "collect_terminal_errors", lambda: ([], ["TERMINAL_WARNING"]))
    start = time.monotonic()
    try:
        bundle = collector.collect_context(ContextRequest(include_screen=True, include_terminal=True))
        assert time.monotonic() - start < 0.5
        assert set(bundle.warnings) == {"TIMEOUT_SCREEN", "TERMINAL_WARNING"}
    finally:
        release.set()


def test_live_dispatch_respects_selected_sources(live, monkeypatch):
    screen = Mock(side_effect=AssertionError("screen deselected"))
    monkeypatch.setattr(collector, "capture_screen", screen)
    monkeypatch.setattr(collector, "collect_terminal_errors", lambda: ([], ["LIVE_TERMINAL"]))
    bundle = perception.collect_context(ContextRequest(include_screen=False, include_terminal=True))
    assert bundle.warnings == ["LIVE_TERMINAL"]
    screen.assert_not_called()


def test_github_rate_limit(monkeypatch):
    from perception import github
    response = Mock(status_code=429, headers={"X-RateLimit-Remaining": "0"})
    monkeypatch.setattr(github.requests, "get", Mock(return_value=response))
    value, warnings = github.fetch_pull_request(GithubTarget(repo="owner/repo", pr_number=1))
    assert value is None and warnings == ["GITHUB_RATE_LIMITED"]


def test_missing_tesseract_returns_screenshot_warning(monkeypatch, tmp_path):
    from perception import screen
    class Capture:
        monitors = [{"width": 1, "height": 1}] * 2
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def grab(self, monitor): return Mock(rgb=b"\0\0\0", size=(1, 1))
    monkeypatch.setattr(screen.mss, "MSS", Capture)
    monkeypatch.setattr(screen, "is_tesseract_available", lambda: False)
    context, warnings = screen.capture_screen(output_dir=tmp_path)
    assert context.screenshot_path and "TESSERACT_NOT_FOUND" in warnings


def test_terminal_traceback_and_redaction():
    from perception.terminal import parse_terminal_errors
    errors = parse_terminal_errors('Traceback (most recent call last):\n  File "app.py", line 2, in run\n    fail()\nValueError: password=supersecret123')
    assert errors[0].file == "app.py"
    assert "supersecret123" not in errors[0].raw_excerpt


@pytest.mark.asyncio
async def test_cancellation_remains_responsive_during_live_collection(live, monkeypatch, async_client):
    started = threading.Event()
    release = threading.Event()
    from shared.schemas import ContextBundle
    from datetime import datetime, timezone
    def slow_collect(req):
        started.set()
        release.wait(2)
        return ContextBundle(collected_at=datetime.now(timezone.utc))
    monkeypatch.setattr(perception, "collect_context", slow_collect)
    try:
        created = await async_client.post('/api/tasks', json={"command": "inspect"})
        task_id = created.json()['task_id']
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        result = await asyncio.wait_for(async_client.post(f'/api/tasks/{task_id}/cancel'), timeout=0.5)
        assert result.json()['state'] == 'cancelled'
    finally:
        release.set()
