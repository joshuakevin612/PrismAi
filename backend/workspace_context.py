"""Read bounded, redacted source files explicitly referenced by collected errors."""
from pathlib import Path
from backend.context_budget import extract_traceback_filenames
from perception.redactor import redact_secrets
from shared.schemas import PatchFile
import difflib
from shared.paths import sensitive_path


def read_workspace_files(bundle, allowed_root: str) -> dict[str, str]:
    root = Path(allowed_root).resolve()
    remaining = 12_000
    files = {}
    for name in sorted(extract_traceback_filenames(bundle.terminal_errors))[:8]:
        try:
            path = (root / name).resolve(strict=True)
            relative = path.relative_to(root)
            if sensitive_path(Path(name)) or sensitive_path(relative) or not path.is_file():
                continue
            if path.stat().st_size > 128_000:
                continue
            content = redact_secrets(path.read_text(encoding='utf-8'))
            if len(content) > remaining:
                continue  # Never present an incomplete file as a patch source.
            files[relative.as_posix()] = content
            remaining -= len(content)
        except (OSError, ValueError, UnicodeError):
            continue
    return files


def materialize_edit(edit, allowed_root: str) -> PatchFile:
    """Generate exact reviewable diffs from one unambiguous model replacement."""
    root = Path(allowed_root).resolve()
    path = (root / edit.path).resolve()
    relative = path.relative_to(root)
    if not relative.parts or sensitive_path(Path(edit.path)) or sensitive_path(relative):
        raise ValueError('Protected patch target')
    if path.exists() and path.stat().st_size > 128_000:
        raise ValueError('Patch source too large')
    original = path.read_text(encoding='utf-8') if path.exists() else ''
    if not edit.old_text:
        if path.exists():
            raise ValueError('Cannot replace an existing file without matching source')
        updated = edit.new_text
    else:
        if original.count(edit.old_text) != 1:
            raise ValueError('Original text must match exactly once')
        updated = original.replace(edit.old_text, edit.new_text, 1)
    if original == updated:
        raise ValueError('Edit makes no change')
    lines = difflib.unified_diff(original.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile='a/' + relative.as_posix(), tofile='b/' + relative.as_posix())
    diff = ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in lines)
    return PatchFile(path=relative.as_posix(), unified_diff=diff)
