"""
perception/sandbox.py
M1 patch execution adapted to M2 approval tokens.
Checks paths and patch contents; live subprocesses are denied until OS isolation
is available.
"""

import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

from shared.schemas import ActionRequest, ActionResult, PatchFile
from perception.redactor import redact_secrets
from perception.patching import apply_verified_diff, validate_diff
from shared.paths import sensitive_path, safe_workspace

# Environment variables
ENV_ALLOWED_ROOT = "ALLOWED_ROOT"

# Allowed commands/executables (basenames)
ALLOWED_BINARIES = {
    "python",
    "python3",
    "py",
    "pytest",
    "npm",
    "node",
    "npx",
    "git",
    "ruff",
    "flake8",
    "black",
    "mypy",
    "pip",
    "pip3",
    "poetry",
    "yarn",
    "pnpm",
    "cargo",
    "go",
}

# Blocked binaries and network tools
BLOCKED_BINARIES = {
    "rm",
    "del",
    "rmdir",
    "sudo",
    "su",
    "curl",
    "wget",
    "nc",
    "netcat",
    "bash",
    "sh",
    "powershell",
    "cmd",
    "chmod",
    "chown",
    "ssh",
    "scp",
    "ftp",
    "telnet",
    "dd",
    "format",
    "mkfs",
}

# Shell metacharacters regex (checked even though shell=False to prevent subshell/pipe tricks)
SHELL_META_REGEX = re.compile(r"[;&|`$<>\n\r]")


def get_allowed_root() -> Path:
    """Returns canonical resolved allowed root directory."""
    root_str = os.getenv(ENV_ALLOWED_ROOT, os.getcwd())
    return Path(root_str).resolve()


def is_path_inside_root(target_path: Path, root_path: Path) -> bool:
    """Checks whether target_path resides within root_path without escaping."""
    try:
        resolved_target = target_path.resolve()
        resolved_root = root_path.resolve()
        return resolved_target.is_relative_to(resolved_root)
    except Exception:
        return False


def validate_command(command: Optional[List[str]]) -> Tuple[bool, Optional[str]]:
    """Validates command against security allowlist and forbidden metacharacters."""
    if not command or not isinstance(command, list) or len(command) == 0:
        return False, "EMPTY_OR_INVALID_COMMAND"

    raw_binary = command[0].strip()
    binary_name = Path(raw_binary).name.lower()
    # Strip extension (e.g. python.exe -> python)
    if binary_name.endswith(".exe"):
        binary_name = binary_name[:-4]

    if binary_name in BLOCKED_BINARIES:
        return False, f"COMMAND_FORBIDDEN: {binary_name}"

    if binary_name not in ALLOWED_BINARIES:
        return False, f"COMMAND_NOT_ALLOWLISTED: {binary_name}"

    # Check for shell metacharacters in arguments
    full_cmd_str = " ".join(command)
    if SHELL_META_REGEX.search(full_cmd_str):
        return False, "SHELL_METACHARACTERS_DETECTED"

    # Block destructive rm-like arguments
    for arg in command:
        arg_lower = arg.lower()
        if arg_lower in ("-rf", "-fr", "/s", "/q") and ("rm" in command[0] or "del" in command[0]):
            return False, "DESTRUCTIVE_COMMAND_DETECTED"

    return True, None


def validate_patch(patch: Optional[PatchFile], working_dir: Path, allowed_root: Path) -> Tuple[bool, Optional[str]]:
    """Validates patch target paths against directory traversal."""
    if not patch or not patch.path:
        return False, "EMPTY_PATCH"

    # Check file path traversal
    file_path = (working_dir / patch.path).resolve()
    if not is_path_inside_root(file_path, allowed_root):
        return False, "PATCH_OUTSIDE_ALLOWED_ROOT"

    # Protected system files
    relative_str = str(file_path.relative_to(allowed_root)).replace("\\", "/")
    if sensitive_path(Path(patch.path)) or sensitive_path(file_path.relative_to(allowed_root)):
        return False, f"CANNOT_PATCH_PROTECTED_FILE: {relative_str}"

    # Verify diff headers if present
    diff = patch.unified_diff or ""
    for line in diff.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            header_target = line[4:].strip().split("\t")[0]
            if header_target not in ("/dev/null", "dev/null"):
                # Clean git diff prefixes a/ and b/
                cleaned = re.sub(r"^[ab]/", "", header_target)
                target_check = (working_dir / cleaned).resolve()
                if not is_path_inside_root(target_check, allowed_root):
                    return False, f"PATCH_HEADER_OUTSIDE_ALLOWED_ROOT: {cleaned}"
                if target_check != file_path:
                    return False, "PATCH_HEADER_TARGET_MISMATCH"

    try:
        validate_diff(file_path, diff)
    except (OSError, ValueError, UnicodeError):
        return False, 'PATCH_INVALID_OR_STALE'
    return True, None


def validate_action(req: ActionRequest, allowed_root=None) -> Tuple[bool, Optional[str]]:
    """
    Dry-run policy check with NO side effects.
    M2 calls this before showing a proposal to verify it won't be auto-denied.
    """
    allowed_root = Path(allowed_root).resolve() if allowed_root is not None else get_allowed_root()

    # Validate working directory
    try:
        workdir = Path(req.working_dir or ".").resolve()
    except Exception:
        return False, "INVALID_WORKING_DIRECTORY"

    if not is_path_inside_root(workdir, allowed_root):
        return False, "WORKING_DIR_OUTSIDE_ALLOWED_ROOT"

    if req.kind == "run_command":
        ok, reason = validate_command(req.command)
        if not ok:
            return ok, reason
        try:
            safe_workspace(allowed_root, check_files=True)
        except (OSError, ValueError) as exc:
            return False, str(exc) if isinstance(exc, ValueError) else 'WORKSPACE_SCAN_FAILED'
        # shell=False and an executable allowlist do not confine Python, npm,
        # Git hooks, or child processes. Fail closed until OS isolation exists.
        from perception.container_runtime import availability
        return availability()
    elif req.kind == "apply_patch":
        return validate_patch(req.patch, workdir, allowed_root)
    else:
        return False, f"UNKNOWN_ACTION_KIND: {req.kind}"


def execute(req: ActionRequest, secret=None, allowed_root=None, cancel_event=None) -> ActionResult:
    """
    Executes an approved ActionRequest inside the sandbox.
    Refuses any action without valid approval token or violating security policy.
    Never raises exceptions: returns ActionResult with status and denial_reason if blocked.
    """
    start_ms = time.perf_counter()

    def result(
        status: str,
        exit_code: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
        denial_reason: Optional[str] = None,
    ) -> ActionResult:
        elapsed = int((time.perf_counter() - start_ms) * 1000)
        return ActionResult(
            action_id=req.action_id,
            status=status,  # type: ignore
            exit_code=exit_code,
            stdout=redact_secrets(stdout),
            stderr=redact_secrets(stderr),
            denial_reason=denial_reason,
            duration_ms=elapsed,
        )

    # Use M2's exact payload serialization and shared secret.
    from shared.approval import verify_action
    if not (secret and verify_action(req, secret)):
        return result("denied", denial_reason="INVALID_OR_MISSING_APPROVAL_TOKEN")

    from backend.permissions import command_permissions
    if req.kind == 'apply_patch' and not req.access.modify_files:
        return result('denied', denial_reason='MODIFY_FILES_ACCESS_REQUIRED')
    required = command_permissions(req.command or [])
    if any(not getattr(req.access, capability, False) for capability in required):
        return result('denied', denial_reason='EXECUTION_ACCESS_REQUIRED')

    policy_ok, denial_reason = validate_action(req, allowed_root=allowed_root)
    if not policy_ok:
        return result("denied", denial_reason=denial_reason)

    # 3. Execution
    allowed_root = Path(allowed_root).resolve() if allowed_root is not None else get_allowed_root()
    workdir = Path(req.working_dir or ".").resolve()

    if cancel_event and cancel_event.is_set():
        return result("denied", denial_reason="ACTION_CANCELLED")

    if req.kind == "run_command":
        from perception.container_runtime import execute as execute_isolated
        return execute_isolated(req, allowed_root, cancel_event=cancel_event)

    if req.kind == "apply_patch":
        try:
            assert req.patch is not None
            target_file = (workdir / req.patch.path).resolve()
            apply_verified_diff(target_file, req.patch.unified_diff)
            return result("ok", exit_code=0, stdout=f"Patch applied successfully to {req.patch.path}")
        except Exception as e:
            return result("failed", exit_code=1, stderr=f"Failed to apply patch: {str(e)}")

    return result("denied", denial_reason="UNSUPPORTED_ACTION_KIND")
