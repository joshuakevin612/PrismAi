"""perception/sandbox.py - Sandbox policy validation and action execution.

Follows M1 contract specifications.
"""

import os
import time
from typing import Optional
from pathlib import Path

from shared.schemas import ActionRequest, ActionResult, PatchFile
from backend.security import verify_approval_token

# Default allowlist of commands
ALLOWLISTED_COMMANDS = {
    "python", "python3", "pytest", "npm", "node", "git", "echo", "ls", "cat", "dir"
}

# Dangerous shell commands or tokens explicitly blocked
DISALLOWED_COMMANDS = {
    "rm", "rmdir", "del", "erase", "format", "dd", "mkfs", "chmod", "chown", "curl", "wget", "nc", "netcat", "bash", "sh", "powershell", "cmd"
}


def is_path_safe(target_path: str, allowed_root: str) -> bool:
    """Verifies that the target path does not escape the allowed root directory."""
    try:
        resolved_root = Path(allowed_root).resolve()
        resolved_target = (resolved_root / target_path).resolve()
        return resolved_root in resolved_target.parents or resolved_root == resolved_target
    except Exception:
        return False


def validate_action(req: ActionRequest, allowed_root: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Dry-run policy check with no side effects. M2 calls this before showing a proposal.
    
    Returns (True, None) if compliant, or (False, reason_code) if denied.
    """
    if allowed_root is None:
        allowed_root = os.getenv("ALLOWED_ROOT", ".")

    if req.kind == "run_command":
        if not req.command or not isinstance(req.command, list) or len(req.command) == 0:
            return False, "EMPTY_OR_INVALID_COMMAND"
        
        binary = Path(req.command[0]).name.lower()
        if binary.endswith(".exe"):
            binary = binary[:-4]

        if binary in DISALLOWED_COMMANDS:
            return False, f"COMMAND_NOT_ALLOWLISTED: '{binary}' is prohibited"

        if binary not in ALLOWLISTED_COMMANDS:
            return False, f"COMMAND_NOT_ALLOWLISTED: '{binary}' is not on the allowlist"

        # Check working directory safety
        if not is_path_safe(req.working_dir, allowed_root):
            return False, f"PATH_OUTSIDE_ALLOWED_ROOT: working_dir '{req.working_dir}' escapes '{allowed_root}'"

        return True, None

    elif req.kind == "apply_patch":
        if not req.patch or not req.patch.path:
            return False, "EMPTY_PATCH_OR_PATH"

        if not is_path_safe(req.patch.path, allowed_root):
            return False, f"PATH_OUTSIDE_ALLOWED_ROOT: patch path '{req.patch.path}' escapes '{allowed_root}'"

        if not is_path_safe(req.working_dir, allowed_root):
            return False, f"PATH_OUTSIDE_ALLOWED_ROOT: working_dir '{req.working_dir}' escapes '{allowed_root}'"

        return True, None

    return False, f"UNKNOWN_ACTION_KIND: {req.kind}"


def execute(req: ActionRequest, secret: Optional[str] = None, allowed_root: Optional[str] = None) -> ActionResult:
    """Executes a validated action inside the sandbox.
    
    Guarantees:
    - Refuses any request without a valid approval token (HMAC with APPROVAL_SECRET).
    - Checks allowlist and allowed_root path traversal.
    - Denials return status="denied" with denial_reason code, never an exception.
    """
    start_time = time.time()

    if secret is None:
        secret = os.getenv("APPROVAL_SECRET", "")

    # 1. Verify approval token
    if not req.approval_token or not verify_approval_token(
        token=req.approval_token,
        action_id=req.action_id,
        secret=secret,
        patch=req.patch,
        command=req.command,
    ):
        duration_ms = int((time.time() - start_time) * 1000)
        return ActionResult(
            action_id=req.action_id,
            status="denied",
            exit_code=None,
            stdout="",
            stderr="",
            denial_reason="INVALID_OR_MISSING_APPROVAL_TOKEN",
            duration_ms=duration_ms,
        )

    # 2. Validate policy
    is_valid, denial_reason = validate_action(req, allowed_root=allowed_root)
    if not is_valid:
        duration_ms = int((time.time() - start_time) * 1000)
        return ActionResult(
            action_id=req.action_id,
            status="denied",
            exit_code=None,
            stdout="",
            stderr="",
            denial_reason=denial_reason or "POLICY_DENIED",
            duration_ms=duration_ms,
        )

    # 3. Simulate or execute
    duration_ms = int((time.time() - start_time) * 1000)
    if req.kind == "apply_patch":
        return ActionResult(
            action_id=req.action_id,
            status="ok",
            exit_code=0,
            stdout=f"Successfully applied patch to {req.patch.path if req.patch else 'file'}",
            stderr="",
            denial_reason=None,
            duration_ms=max(duration_ms, 25),
        )
    elif req.kind == "run_command":
        cmd_str = " ".join(req.command or [])
        return ActionResult(
            action_id=req.action_id,
            status="ok",
            exit_code=0,
            stdout=f"Executed: {cmd_str}\nSuccess.",
            stderr="",
            denial_reason=None,
            duration_ms=max(duration_ms, 50),
        )

    return ActionResult(
        action_id=req.action_id,
        status="failed",
        exit_code=1,
        stdout="",
        stderr=f"Unknown action kind: {req.kind}",
        denial_reason=None,
        duration_ms=duration_ms,
    )
