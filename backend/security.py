"""backend/security.py - HMAC approval token generation and verification."""

import hashlib
import hmac
from typing import Optional
from shared.schemas import PatchFile


def compute_action_payload_hash(patch: Optional[PatchFile] = None, command: Optional[list[str]] = None) -> str:
    """Computes a deterministic SHA256 hex digest of the patch or command payload."""
    hasher = hashlib.sha256()

    if patch is not None:
        hasher.update(b"patch:")
        hasher.update(patch.path.encode("utf-8"))
        hasher.update(b":")
        hasher.update(patch.unified_diff.encode("utf-8"))
    elif command is not None:
        hasher.update(b"command:")
        hasher.update("\x00".join(command).encode("utf-8"))
    else:
        hasher.update(b"empty")

    return hasher.hexdigest()


def generate_approval_token(
    action_id: str,
    secret: str,
    patch: Optional[PatchFile] = None,
    command: Optional[list[str]] = None,
) -> str:
    """Generates an HMAC-SHA256 approval token for an action."""
    payload_hash = compute_action_payload_hash(patch=patch, command=command)
    message = f"{action_id}:{payload_hash}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_approval_token(
    token: str,
    action_id: str,
    secret: str,
    patch: Optional[PatchFile] = None,
    command: Optional[list[str]] = None,
) -> bool:
    """Verifies that the provided approval token matches the expected HMAC."""
    expected_token = generate_approval_token(
        action_id=action_id,
        secret=secret,
        patch=patch,
        command=command,
    )
    return hmac.compare_digest(token, expected_token)
