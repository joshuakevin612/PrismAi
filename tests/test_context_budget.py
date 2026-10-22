"""tests/test_context_budget.py - Tests context budgeting, prioritization, and truncation."""

from datetime import datetime, timezone
from shared.schemas import ContextBundle, DiffFile, PullRequestContext, ScreenContext, TerminalError
from backend.context_budget import (
    DIFFS_BUDGET_CHARS,
    OCR_BUDGET_CHARS,
    budget_diff_files,
    extract_traceback_filenames,
    prepare_prompt_context,
)


def test_ocr_budgeting():
    huge_ocr = "A" * 6000
    bundle = ContextBundle(
        schema_version="1.0",
        collected_at=datetime.now(timezone.utc),
        screen=ScreenContext(
            captured_at=datetime.now(timezone.utc),
            monitor=1,
            width=1920,
            height=1080,
            ocr_text=huge_ocr,
        ),
    )
    prompt_ctx = prepare_prompt_context("run tests", bundle)
    assert len(prompt_ctx["ocr_text"]) <= OCR_BUDGET_CHARS + 50
    assert prompt_ctx["ocr_truncated"] is True


def test_diff_budgeting_prioritizes_tracebacks():
    terminal_errors = [
        TerminalError(
            exception_type="ValueError",
            message="bad val",
            file="services/important.py",
            line=10,
            raw_excerpt='File "services/important.py", line 10 in func',
        )
    ]
    priority_files = extract_traceback_filenames(terminal_errors)
    assert "services/important.py" in priority_files

    # Create 3 diff files, 2 are huge, 1 is the traceback file
    f_unrelated_1 = DiffFile(
        path="other/huge1.py",
        status="modified",
        additions=100,
        deletions=0,
        patch="X" * 6000,
    )
    f_traceback = DiffFile(
        path="services/important.py",
        status="modified",
        additions=10,
        deletions=2,
        patch="Y" * 3000,
    )
    f_unrelated_2 = DiffFile(
        path="other/huge2.py",
        status="modified",
        additions=100,
        deletions=0,
        patch="Z" * 6000,
    )

    budgeted = budget_diff_files(
        [f_unrelated_1, f_traceback, f_unrelated_2],
        priority_filenames=priority_files,
        max_budget=8000,
    )

    # High priority file should be first and fully included
    assert budgeted[0].path == "services/important.py"
    assert budgeted[0].patch == "Y" * 3000
    assert budgeted[0].truncated is False

    # Second file gets remaining budget (~5000 chars) and is marked truncated
    assert budgeted[1].path == "other/huge1.py"
    assert budgeted[1].truncated is True

    # Third file has 0 budget left, patch dropped, truncated is True
    assert budgeted[2].path == "other/huge2.py"
    assert budgeted[2].patch is None
    assert budgeted[2].truncated is True
