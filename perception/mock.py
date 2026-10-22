"""perception/mock.py - Mock implementation of Member 1 perception module.

Ships for Day 2 integration so M2 and M3 can test without hardware/external dependencies.
Returns a canned ContextBundle (Python traceback + PR diff) and execute returning 'ok'.
"""

from datetime import datetime, timezone
from typing import Optional

from shared.schemas import (
    ContextBundle,
    ContextRequest,
    DiffFile,
    ProcessInfo,
    PullRequestContext,
    ScreenContext,
    TerminalError,
    ActionRequest,
    ActionResult,
)
from perception.sandbox import execute as sandbox_execute


def collect_mock_context(req: ContextRequest) -> ContextBundle:
    """Returns a deterministic ContextBundle with a Python traceback and a PR diff."""
    now = datetime.now(timezone.utc)

    screen: Optional[ScreenContext] = None
    if req.include_screen:
        screen = ScreenContext(
            captured_at=now,
            monitor=1,
            width=1920,
            height=1080,
            ocr_text="Traceback (most recent call last):\n  File \"app/main.py\", line 15, in index\n    res = calculate_total(items)\nKeyError: 'price'\n",
            ocr_confidence=0.98,
            screenshot_path="fixtures/mock_screenshot.png",
        )

    terminal_errors: list[TerminalError] = []
    if req.include_terminal:
        terminal_errors.append(
            TerminalError(
                exception_type="KeyError",
                message="'price'",
                file="app/main.py",
                line=15,
                raw_excerpt="Traceback (most recent call last):\n  File \"app/main.py\", line 15, in index\n    res = calculate_total(items)\nKeyError: 'price'",
            )
        )

    processes: list[ProcessInfo] = []
    if req.include_processes:
        processes.append(
            ProcessInfo(
                pid=1234,
                name="python",
                cmdline="python -m uvicorn app.main:app",
                cpu_percent=1.2,
                mem_mb=85.4,
            )
        )

    pr: Optional[PullRequestContext] = None
    if req.github:
        pr = PullRequestContext(
            repo=req.github.repo,
            number=req.github.pr_number,
            title="Refactor pricing service",
            body="Adds support for optional discounts and tax calculation",
            base="main",
            head="feature/pricing",
            files=[
                DiffFile(
                    path="app/main.py",
                    status="modified",
                    additions=5,
                    deletions=2,
                    patch="--- a/app/main.py\n+++ b/app/main.py\n@@ -14,2 +14,5 @@\n-def calculate_total(items):\n-    return sum(item['price'] for item in items)\n+def calculate_total(items):\n+    return sum(item.get('price', 0) for item in items)\n",
                    truncated=False,
                )
            ],
        )

    return ContextBundle(
        schema_version="1.0",
        collected_at=now,
        screen=screen,
        terminal_errors=terminal_errors,
        processes=processes,
        pull_request=pr,
        warnings=[],
    )


def health() -> dict[str, bool]:
    return {
        "tesseract": True,
        "github_token": True,
        "sandbox": True,
    }


def execute(req: ActionRequest) -> ActionResult:
    """Mock execute returning 'ok'."""
    return sandbox_execute(req)
