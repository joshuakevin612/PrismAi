"""
perception/terminal.py
Terminal error and exception extractor.
Parses Python, Node.js, and general compiler/runtime tracebacks.
Ensures max 4000 chars raw_excerpt, redaction, and non-raising execution.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from shared.schemas import TerminalError
from perception.redactor import redact_secrets

MAX_EXCERPT_CHARS = 4000

# Regex for Python tracebacks
PYTHON_TRACEBACK_RE = re.compile(
    r"(Traceback \(most recent call last\):[\s\S]+?(?:^[a-zA-Z_][a-zA-Z0-9_\.]*(?:Error|Exception|Interrupt|Exit|Warning)[\s\S]*?$))",
    re.MULTILINE,
)

PYTHON_FILE_LINE_RE = re.compile(
    r'File "([^"]+)", line (\d+)(?:, in .*)?'
)

PYTHON_EXC_TYPE_MSG_RE = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_\.]*(?:Error|Exception|Interrupt|Exit|Warning))(?::\s*(.*))?$"
)

# Regex for Node.js / V8 stack traces
NODE_ERROR_RE = re.compile(
    r"((?:[a-zA-Z_$][a-zA-Z0-9_$]*Error|[A-Z][a-zA-Z0-9_$]*Exception): [^\n]+\n(?:\s+at [^\n]+\n?)+)"
)

NODE_FILE_LINE_RE = re.compile(
    r"\bat (?:.+ \()?((?:[a-zA-Z]:)?[^:)\n]+):(\d+):(\d+)\)?"
)


def extract_python_errors(text: str) -> List[TerminalError]:
    """Finds Python tracebacks in terminal text and structures them."""
    errors: List[TerminalError] = []

    for match in PYTHON_TRACEBACK_RE.finditer(text):
        raw_block = match.group(1).strip()
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        if not lines:
            continue

        last_line = lines[-1]
        exc_type: Optional[str] = None
        message: str = last_line

        exc_match = PYTHON_EXC_TYPE_MSG_RE.match(last_line)
        if exc_match:
            exc_type = exc_match.group(1)
            message = exc_match.group(2) or ""

        # Find the last File "...", line X in the traceback (innermost frame)
        file_matches = list(PYTHON_FILE_LINE_RE.finditer(raw_block))
        file_path: Optional[str] = None
        line_num: Optional[int] = None
        if file_matches:
            last_file_match = file_matches[-1]
            file_path = last_file_match.group(1)
            try:
                line_num = int(last_file_match.group(2))
            except ValueError:
                line_num = None

        excerpt = redact_secrets(raw_block[:MAX_EXCERPT_CHARS])
        errors.append(
            TerminalError(
                exception_type=exc_type,
                message=redact_secrets(message),
                file=file_path,
                line=line_num,
                raw_excerpt=excerpt,
            )
        )

    return errors


def extract_node_errors(text: str) -> List[TerminalError]:
    """Finds Node.js/JS stack traces in terminal text and structures them."""
    errors: List[TerminalError] = []

    for match in NODE_ERROR_RE.finditer(text):
        raw_block = match.group(1).strip()
        lines = raw_block.splitlines()
        first_line = lines[0] if lines else ""

        exc_type = None
        message = first_line
        if ":" in first_line:
            parts = first_line.split(":", 1)
            exc_type = parts[0].strip()
            message = parts[1].strip()

        file_match = NODE_FILE_LINE_RE.search(raw_block)
        file_path = None
        line_num = None
        if file_match:
            file_path = file_match.group(1)
            try:
                line_num = int(file_match.group(2))
            except ValueError:
                line_num = None

        excerpt = redact_secrets(raw_block[:MAX_EXCERPT_CHARS])
        errors.append(
            TerminalError(
                exception_type=exc_type,
                message=redact_secrets(message),
                file=file_path,
                line=line_num,
                raw_excerpt=excerpt,
            )
        )

    return errors


def parse_terminal_errors(raw_text: str) -> List[TerminalError]:
    """Parses text for any known error traces."""
    if not raw_text:
        return []

    errors = extract_python_errors(raw_text)
    if not errors:
        errors = extract_node_errors(raw_text)

    # If no structured stack trace was found but text contains explicit ERROR/FATAL lines:
    if not errors:
        generic_error_lines = []
        for line in raw_text.splitlines():
            line_str = line.strip()
            if any(k in line_str.upper() for k in ("ERROR:", "FATAL:", "FAILED:", "PANIC:")):
                generic_error_lines.append(line_str)

        if generic_error_lines:
            summary = "\n".join(generic_error_lines[:5])
            errors.append(
                TerminalError(
                    exception_type="GeneralError",
                    message=redact_secrets(generic_error_lines[0]),
                    file=None,
                    line=None,
                    raw_excerpt=redact_secrets(summary[:MAX_EXCERPT_CHARS]),
                )
            )

    return errors


def collect_terminal_errors(
    search_dirs: Optional[List[Path]] = None,
) -> Tuple[List[TerminalError], List[str]]:
    """
    Scans common terminal log locations, .pytest_cache, or stderr dumps.
    Returns (errors, warnings). Never raises.
    """
    warnings: List[str] = []
    errors: List[TerminalError] = []

    try:
        from backend.config import settings
        root = Path(settings.ALLOWED_ROOT).resolve()
        # Check standard log or error file locations if present
        candidates = [
            root / "terminal_stderr.log",
            root / "error.log",
            root / ".prism/terminal.log",
        ]
        if search_dirs:
            for sdir in search_dirs:
                candidates.extend(sdir.glob("*.log"))

        for path in candidates:
            if path.is_file():
                try:
                    if not path.resolve().is_relative_to(root):
                        continue
                    with path.open('rb') as stream:
                        stream.seek(max(0, path.stat().st_size - 64_000))
                        content = stream.read(64_000).decode('utf-8', errors='replace')
                    found = parse_terminal_errors(content)
                    errors.extend(found)
                except Exception as read_err:
                    warnings.append(f"LOG_READ_ERROR_{path.name}: {type(read_err).__name__}")

    except Exception as e:
        warnings.append(f"TERMINAL_COLLECT_FAILED: {type(e).__name__}")

    return errors, warnings
