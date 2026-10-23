"""
perception/mock.py
Mock implementation for Day 2 integration checkpoint with Member 2.
Returns canned realistic context (Python traceback + PR diff) and successful execution.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

from shared.schemas import (
    ActionRequest,
    ActionResult,
    ContextBundle,
    ContextRequest,
    DiffFile,
    ProcessInfo,
    PullRequestContext,
    ScreenContext,
    TerminalError,
)

SAMPLE_TRACEBACK = """Traceback (most recent call last):
  File "src/api/routes.py", line 42, in get_user_profile
    user = db.query(User).filter_by(id=user_id).one()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "sqlalchemy/orm/query.py", line 2843, in one
    raise exc.NoResultFound("No row was found when one was required")
sqlalchemy.exc.NoResultFound: No row was found when one was required"""

SAMPLE_DIFF = """--- a/src/api/routes.py
+++ b/src/api/routes.py
@@ -39,5 +39,8 @@
 def get_user_profile(user_id: int):
-    user = db.query(User).filter_by(id=user_id).one()
+    user = db.query(User).filter_by(id=user_id).one_or_none()
+    if not user:
+        raise HTTPException(status_code=404, detail="User not found")
     return user"""


def collect_context(req: ContextRequest) -> ContextBundle:
    """Mock context collector returning a fixed realistic bundle for M2 testing."""
    now = datetime.now(timezone.utc)

    screen = ScreenContext(
        captured_at=now,
        monitor=1,
        width=1920,
        height=1080,
        ocr_text="VS Code - routes.py - sqlalchemy.exc.NoResultFound: No row was found",
        ocr_confidence=0.96,
        screenshot_path="fixtures/mock_screenshot.png",
    ) if req.include_screen else None

    terminal_errors = [
        TerminalError(
            exception_type="sqlalchemy.exc.NoResultFound",
            message="No row was found when one was required",
            file="src/api/routes.py",
            line=42,
            raw_excerpt=SAMPLE_TRACEBACK,
        )
    ] if req.include_terminal else []

    processes = [
        ProcessInfo(
            pid=4102,
            name="python.exe",
            cmdline="python -m uvicorn main:app --reload --port 8000",
            cpu_percent=1.5,
            mem_mb=128.4,
        ),
        ProcessInfo(
            pid=9840,
            name="node.exe",
            cmdline="node vite --port 5173",
            cpu_percent=0.8,
            mem_mb=92.1,
        ),
    ] if req.include_processes else []

    pull_request = PullRequestContext(
        repo=req.github.repo if req.github else "prism-ai/core",
        number=req.github.pr_number if req.github else 101,
        title="fix(api): handle missing user gracefully in profile endpoint",
        body="Resolves NoResultFound exception by using one_or_none and raising 404.",
        base="main",
        head="fix/user-not-found",
        files=[
            DiffFile(
                path="src/api/routes.py",
                status="modified",
                additions=4,
                deletions=1,
                patch=SAMPLE_DIFF,
                truncated=False,
            )
        ],
    ) if req.github else None

    return ContextBundle(
        schema_version="1.0",
        collected_at=now,
        screen=screen,
        terminal_errors=terminal_errors,
        processes=processes,
        pull_request=pull_request,
        warnings=[],
    )


def execute(req: ActionRequest) -> ActionResult:
    """Mock executor returning 'ok' for M2 testing."""
    return ActionResult(
        action_id=req.action_id,
        status="ok",
        exit_code=0,
        stdout=f"Mock action '{req.action_id}' ({req.kind}) executed successfully.",
        stderr="",
        denial_reason=None,
        duration_ms=15,
    )


def validate_action(req: ActionRequest) -> Tuple[bool, Optional[str]]:
    """Mock validator returning true."""
    return True, None


def health() -> dict[str, bool]:
    """Mock health endpoint returning all systems operational."""
    return {
        "tesseract": True,
        "github_token": True,
        "sandbox": True,
    }
