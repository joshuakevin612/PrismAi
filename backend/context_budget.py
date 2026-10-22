"""backend/context_budget.py - Enforces context limits and constructs safe prompts.

Enforces:
- OCR text truncated to ~4k chars
- Diffs truncated to ~8k chars total
- Prioritizes terminal errors and files named in tracebacks
- Passes `truncated` flags to prompt
- Quotes screen/PR text to mitigate prompt-injection risk
"""

from typing import Optional
from shared.schemas import ContextBundle, ContextSummary, DiffFile, TerminalError


OCR_BUDGET_CHARS = 4000
DIFFS_BUDGET_CHARS = 8000


def build_context_summary(bundle: ContextBundle) -> ContextSummary:
    """Creates a lightweight ContextSummary for TaskView without massive blobs."""
    has_screenshot = (
        bundle.screen is not None and bool(bundle.screen.screenshot_path)
    )
    ocr_excerpt = ""
    if bundle.screen and bundle.screen.ocr_text:
        ocr_excerpt = bundle.screen.ocr_text[:1000]

    pr_title: Optional[str] = None
    pr_files: list[str] = []
    if bundle.pull_request:
        pr_title = bundle.pull_request.title
        pr_files = [f.path for f in bundle.pull_request.files]

    return ContextSummary(
        has_screenshot=has_screenshot,
        ocr_excerpt=ocr_excerpt,
        terminal_errors=bundle.terminal_errors,
        pr_title=pr_title,
        pr_files=pr_files,
        warnings=bundle.warnings,
    )


def extract_traceback_filenames(terminal_errors: list[TerminalError]) -> set[str]:
    """Finds paths referenced in terminal error messages or tracebacks."""
    filenames: set[str] = set()
    for err in terminal_errors:
        if err.file:
            filenames.add(err.file.replace("\\", "/").strip())
        # Also check raw excerpt for common traceback patterns e.g. File "path/to/file.py", line 12
        if err.raw_excerpt:
            import re
            matches = re.findall(r'File "([^"]+)"', err.raw_excerpt)
            for m in matches:
                filenames.add(m.replace("\\", "/").strip())
    return filenames


def budget_diff_files(
    files: list[DiffFile],
    priority_filenames: set[str],
    max_budget: int = DIFFS_BUDGET_CHARS,
) -> list[DiffFile]:
    """Budgets diffs prioritizing files referenced in tracebacks."""
    # Partition files into high priority and standard priority
    priority_files: list[DiffFile] = []
    other_files: list[DiffFile] = []

    for f in files:
        norm_path = f.path.replace("\\", "/").strip()
        # Check if file path matches or ends with any priority filename
        is_priority = any(
            norm_path == p or norm_path.endswith("/" + p) or p.endswith("/" + norm_path)
            for p in priority_filenames
        )
        if is_priority:
            priority_files.append(f)
        else:
            other_files.append(f)

    ordered = priority_files + other_files
    budgeted: list[DiffFile] = []
    used_chars = 0

    for item in ordered:
        patch_text = item.patch or ""
        patch_len = len(patch_text)
        already_truncated = item.truncated

        remaining_budget = max_budget - used_chars
        if remaining_budget <= 0:
            # Drop patch content for remaining files, mark truncated
            budgeted.append(
                DiffFile(
                    path=item.path,
                    status=item.status,
                    additions=item.additions,
                    deletions=item.deletions,
                    patch=None,
                    truncated=True,
                )
            )
        elif patch_len > remaining_budget:
            # Partially include up to budget
            truncated_patch = patch_text[:remaining_budget] + "\n... [diff truncated to stay within context budget]"
            used_chars += len(truncated_patch)
            budgeted.append(
                DiffFile(
                    path=item.path,
                    status=item.status,
                    additions=item.additions,
                    deletions=item.deletions,
                    patch=truncated_patch,
                    truncated=True,
                )
            )
        else:
            used_chars += patch_len
            budgeted.append(
                DiffFile(
                    path=item.path,
                    status=item.status,
                    additions=item.additions,
                    deletions=item.deletions,
                    patch=item.patch,
                    truncated=already_truncated,
                )
            )

    return budgeted


def prepare_prompt_context(
    command: str,
    bundle: ContextBundle,
) -> dict:
    """Prepares structured, budgeted, and sanitized context dictionary for the LLM."""
    ocr_text = ""
    ocr_truncated = False
    if bundle.screen and bundle.screen.ocr_text:
        if len(bundle.screen.ocr_text) > OCR_BUDGET_CHARS:
            ocr_text = bundle.screen.ocr_text[:OCR_BUDGET_CHARS] + "\n... [OCR text truncated]"
            ocr_truncated = True
        else:
            ocr_text = bundle.screen.ocr_text

    priority_filenames = extract_traceback_filenames(bundle.terminal_errors)

    budgeted_diffs: list[DiffFile] = []
    pr_metadata = None
    if bundle.pull_request:
        budgeted_diffs = budget_diff_files(
            bundle.pull_request.files,
            priority_filenames=priority_filenames,
            max_budget=DIFFS_BUDGET_CHARS,
        )
        pr_metadata = {
            "repo": bundle.pull_request.repo,
            "number": bundle.pull_request.number,
            "title": bundle.pull_request.title,
            "body": bundle.pull_request.body,
            "base": bundle.pull_request.base,
            "head": bundle.pull_request.head,
            "files": [f.model_dump() for f in budgeted_diffs],
        }

    return {
        "command": command,
        "ocr_text": ocr_text,
        "ocr_truncated": ocr_truncated,
        "terminal_errors": [err.model_dump() for err in bundle.terminal_errors],
        "processes": [p.model_dump() for p in bundle.processes],
        "pull_request": pr_metadata,
        "warnings": bundle.warnings,
    }
