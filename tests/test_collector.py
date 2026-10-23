"""
tests/test_collector.py
Tests context collection orchestrator, terminal parsing, and partial failure handling.
"""

import time
from shared.schemas import ContextRequest, GithubTarget
from perception.collector import collect_context
from perception.terminal import parse_terminal_errors
from perception import health


def test_collect_context_timeout_guarantee():
    req = ContextRequest(
        include_screen=True,
        include_terminal=True,
        include_processes=True,
        github=None,
    )
    start = time.perf_counter()
    bundle = collect_context(req)
    duration = time.perf_counter() - start

    # Guarantees return strictly within 8 s
    assert duration < 8.0
    assert bundle.schema_version == "1.0"
    assert bundle.collected_at is not None
    assert isinstance(bundle.warnings, list)


def test_terminal_traceback_parsing():
    sample_traceback = """Traceback (most recent call last):
  File "src/server/handler.py", line 87, in handle_request
    result = compute_metrics(data)
             ^^^^^^^^^^^^^^^^^^^^^
  File "src/server/metrics.py", line 12, in compute_metrics
    return 100 / count
           ~~~~^~~~~~~
ZeroDivisionError: division by zero"""

    errors = parse_terminal_errors(sample_traceback)
    assert len(errors) == 1
    err = errors[0]
    assert err.exception_type == "ZeroDivisionError"
    assert "division by zero" in err.message
    assert err.file == "src/server/metrics.py"
    assert err.line == 12
    assert "division by zero" in err.raw_excerpt
    assert len(err.raw_excerpt) <= 4000


def test_non_raising_on_invalid_github():
    # Calling non-existent repo or unauthenticated rate-limited should never raise
    req = ContextRequest(
        include_screen=False,
        include_terminal=False,
        include_processes=False,
        github=GithubTarget(repo="prism-ai-nonexistent-org/nonexistent-repo", pr_number=99999),
    )
    bundle = collect_context(req)
    assert bundle.pull_request is None
    assert len(bundle.warnings) > 0


def test_health_check_surface():
    status = health()
    assert isinstance(status, dict)
    assert "tesseract" in status
    assert "github_token" in status
    assert "sandbox" in status
