"""backend/security.py - HMAC approval token generation and verification."""

from typing import Optional
from shared.schemas import ActionRequest, PatchFile
from perception.sandbox import (
    generate_approval_token as p_generate_approval_token,
    verify_approval_token as p_verify_approval_token,
)


def generate_approval_token(
    action_id: str,
    secret: Optional[str] = None,
    patch: Optional[PatchFile] = None,
    command: Optional[list[str]] = None,
    kind: Optional[str] = None,
) -> str:
    """Generates an HMAC-SHA256 approval token for an action matching Member 1 sandbox."""
    if kind is None:
        kind = "apply_patch" if patch is not None else "run_command"
    return p_generate_approval_token(
        action_id=action_id,
        kind=kind,
        command=command,
        patch=patch,
        secret=secret,
    )


def verify_approval_token(
    token: str,
    action_id: str,
    secret: Optional[str] = None,
    patch: Optional[PatchFile] = None,
    command: Optional[list[str]] = None,
    kind: Optional[str] = None,
) -> bool:
    """Verifies that the provided approval token matches the expected HMAC."""
    if kind is None:
        kind = "apply_patch" if patch is not None else "run_command"
    dummy_req = ActionRequest(
        action_id=action_id,
        kind=kind,
        patch=patch,
        command=command,
        working_dir="",
        approval_token=token,
    )
    return p_verify_approval_token(dummy_req, secret=secret)
