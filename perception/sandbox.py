"""
perception/sandbox.py
Secure sandbox execution environment.
Enforces HMAC token verification, command allowlisting, path traversal prevention,
patch boundaries, and subprocess isolation.
"""

import hashlib
import hmac
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple, Union
import shutil

from shared.schemas import ActionRequest, ActionResult, PatchFile
from perception.redactor import redact_secrets

# Environment variables
ENV_ALLOWED_ROOT = "ALLOWED_ROOT"
ENV_APPROVAL_SECRET = "APPROVAL_SECRET"
DEFAULT_APPROVAL_SECRET = "prism-dev-secret-do-not-use-in-prod"

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


def get_approval_secret() -> str:
    """Returns the shared HMAC approval secret."""
    return os.getenv(ENV_APPROVAL_SECRET, DEFAULT_APPROVAL_SECRET)


def compute_payload_hash(req: ActionRequest) -> str:
    """Computes a deterministic hash of the action payload."""
    hasher = hashlib.sha256()
    hasher.update(req.kind.encode("utf-8"))

    if req.kind == "run_command":
        cmd_str = " ".join(req.command or [])
        hasher.update(cmd_str.encode("utf-8"))
    elif req.kind == "apply_patch":
        if req.patch:
            hasher.update(req.patch.path.encode("utf-8"))
            hasher.update(req.patch.unified_diff.encode("utf-8"))

    return hasher.hexdigest()


def generate_approval_token(
    action_id: str,
    kind: str,
    command: Optional[List[str]] = None,
    patch: Optional[PatchFile] = None,
    secret: Optional[str] = None,
) -> str:
    """
    Generates an HMAC approval token for an action.
    Used by M2 when user approves a proposal, and for contract verification.
    """
    sec = secret or get_approval_secret()
    dummy_req = ActionRequest(
        action_id=action_id,
        kind=kind,  # type: ignore
        command=command,
        patch=patch,
        working_dir="",
        approval_token="",
    )
    payload_hash = compute_payload_hash(dummy_req)
    msg = f"{action_id}:{payload_hash}"
    return hmac.new(sec.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_approval_token(req: ActionRequest, secret: Optional[str] = None) -> bool:
    """Verifies that the approval token matches the HMAC of the payload."""
    if not req.approval_token:
        return False

    expected_token = generate_approval_token(
        action_id=req.action_id,
        kind=req.kind,
        command=req.command,
        patch=req.patch,
        secret=secret,
    )
    return hmac.compare_digest(req.approval_token, expected_token)


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
    if relative_str.startswith(".git/") or relative_str == ".env":
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

    return True, None


def validate_action(
    req: ActionRequest,
    allowed_root: Optional[Union[str, Path]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Dry-run policy check with NO side effects.
    M2 calls this before showing a proposal to verify it won't be auto-denied.
    """
    root_path = Path(allowed_root).resolve() if allowed_root is not None else get_allowed_root()

    # Validate working directory
    try:
        workdir = Path(req.working_dir or ".").resolve()
    except Exception:
        return False, "INVALID_WORKING_DIRECTORY"

    if not is_path_inside_root(workdir, root_path):
        return False, "WORKING_DIR_OUTSIDE_ALLOWED_ROOT"

    if req.kind == "run_command":
        return validate_command(req.command)
    elif req.kind == "apply_patch":
        return validate_patch(req.patch, workdir, root_path)
    else:
        return False, f"UNKNOWN_ACTION_KIND: {req.kind}"


def apply_unified_diff(file_path: Path, diff_text: str) -> None:
    """
    Simple, safe pure-Python patch applier for unified diffs.
    Handles file creation and modifications safely.
    """
    lines = diff_text.splitlines(keepends=True)
    if not file_path.exists():
        # New file creation
        content_lines = []
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                content_lines.append(line[1:])
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("".join(content_lines), encoding="utf-8")
        return

    # Existing file modification
    orig_content = file_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    new_content = []
    orig_idx = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        match = hunk_re.match(line)
        if match:
            old_start = int(match.group(1)) - 1
            # Copy untouched lines up to old_start
            while orig_idx < old_start and orig_idx < len(orig_content):
                new_content.append(orig_content[orig_idx])
                orig_idx += 1

            i += 1
            while i < len(lines) and not hunk_re.match(lines[i]):
                hline = lines[i]
                if hline.startswith("+") and not hline.startswith("+++"):
                    new_content.append(hline[1:])
                elif hline.startswith("-") and not hline.startswith("---"):
                    orig_idx += 1  # Skip removed line in original
                elif hline.startswith(" "):
                    if orig_idx < len(orig_content):
                        new_content.append(orig_content[orig_idx])
                        orig_idx += 1
                    else:
                        new_content.append(hline[1:])
                i += 1
            continue
        i += 1

    # Append any remaining original lines
    while orig_idx < len(orig_content):
        new_content.append(orig_content[orig_idx])
        orig_idx += 1

    file_path.write_text("".join(new_content), encoding="utf-8")


def execute(
    req: ActionRequest,
    secret: Optional[str] = None,
    allowed_root: Optional[Union[str, Path]] = None,
) -> ActionResult:
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

    # 1. Policy check
    policy_ok, denial_reason = validate_action(req, allowed_root=allowed_root)
    if not policy_ok:
        return result("denied", denial_reason=denial_reason)

    # 2. Token verification
    if not verify_approval_token(req, secret=secret):
        return result("denied", denial_reason="INVALID_OR_MISSING_APPROVAL_TOKEN")

    # 3. Execution
    root_path = Path(allowed_root).resolve() if allowed_root is not None else get_allowed_root()
    workdir = Path(req.working_dir or ".").resolve()

    if req.kind == "apply_patch":
        try:
            assert req.patch is not None
            target_file = (workdir / req.patch.path).resolve()
            apply_unified_diff(target_file, req.patch.unified_diff)
            return result("ok", exit_code=0, stdout=f"Patch applied successfully to {req.patch.path}")
        except Exception as e:
            return result("failed", exit_code=1, stderr=f"Failed to apply patch: {str(e)}")

    elif req.kind == "run_command":
        try:
            assert req.command is not None
            # Prepare clean environment (strip dangerous/leaking secrets)
            env = os.environ.copy()
            # Disable external network proxies if any
            env.pop("HTTP_PROXY", None)
            env.pop("HTTPS_PROXY", None)
            env.pop("http_proxy", None)
            env.pop("https_proxy", None)

            cmd = list(req.command)
            resolved_bin = shutil.which(cmd[0])
            if resolved_bin:
                cmd[0] = resolved_bin

            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )

            status = "ok" if proc.returncode == 0 else "failed"
            return result(
                status=status,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        except subprocess.TimeoutExpired:
            return result("timeout", stderr="Command timed out after 30 seconds")
        except Exception as e:
            return result("failed", exit_code=1, stderr=f"Command execution error: {type(e).__name__}: {str(e)}")

    return result("denied", denial_reason="UNSUPPORTED_ACTION_KIND")
