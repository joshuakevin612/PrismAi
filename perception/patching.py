"""Apply one unified diff only when source lines and hunk counts match."""
import os
import re
import tempfile
from pathlib import Path


def render_verified_diff(original: str, diff: str) -> str:
    source = original.splitlines(keepends=True)
    lines = diff.splitlines(keepends=True)
    output = []
    cursor = 0
    hunks = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(("diff --git ", "index ", "--- ", "+++ ")):
            index += 1
            continue
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not match:
            raise ValueError("Invalid unified diff header")
        old_start, old_count, new_start, new_count = (int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
        start = old_start if old_count == 0 else old_start - 1
        if start < cursor or start > len(source):
            raise ValueError("Invalid or overlapping hunk")
        output.extend(source[cursor:start])
        cursor = start
        expected_new_start = new_start if new_count == 0 else new_start - 1
        if len(output) != expected_new_start:
            raise ValueError("Incorrect destination offset")
        index += 1
        removed = added = 0
        while index < len(lines) and not lines[index].startswith("@@ "):
            item = lines[index]
            if item[:1] not in {" ", "+", "-"}:
                raise ValueError("Invalid hunk line")
            content = item[1:]
            if index + 1 < len(lines) and lines[index + 1].startswith("\\ No newline at end of file"):
                content = content.rstrip("\r\n")
                index += 1
            if item[0] in {" ", "-"}:
                if cursor >= len(source) or source[cursor] != content:
                    raise ValueError("Patch context does not match current file")
                cursor += 1
                removed += 1
            if item[0] in {" ", "+"}:
                output.append(content)
                added += 1
            index += 1
        if (removed, added) != (old_count, new_count):
            raise ValueError("Hunk line counts do not match")
        hunks += 1
    if not hunks:
        raise ValueError("Patch contains no hunks")
    output.extend(source[cursor:])
    return ''.join(output)


def validate_diff(path: Path, diff: str) -> str:
    if path.exists() and path.stat().st_size > 2_000_000:
        raise ValueError('Patch target exceeds the supported size')
    original = path.read_text(encoding='utf-8') if path.exists() else ''
    return render_verified_diff(original, diff)


def apply_verified_diff(path: Path, diff: str) -> None:
    content = validate_diff(path, diff)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".prism-patch-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
