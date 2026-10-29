"""Team approval contract: capability-bound v2 execution and legacy v1 vectors."""

import hashlib
import hmac
import json
from typing import Optional
from shared.schemas import PatchFile


def sign_action(req, secret: str) -> str:
    """V2 binds the reviewed payload, directory, and exact execution privileges."""
    if not secret:
        raise ValueError('An approval secret is required')
    payload = json.dumps({'version': 2, **req.model_dump(exclude={'approval_token'})},
                         sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()


def verify_action(req, secret: str) -> bool:
    try:
        return bool(secret and req.approval_token.isascii() and hmac.compare_digest(req.approval_token, sign_action(req, secret)))
    except (ValueError, TypeError):
        return False


def compute_action_payload_hash(patch: Optional[PatchFile] = None, command: Optional[list[str]] = None) -> str:
    """Computes a deterministic SHA256 hex digest of the patch or command payload."""
    hasher = hashlib.sha256()

    if (patch is None) == (command is None):
        raise ValueError("An approval must identify exactly one payload kind")
    if command is not None and any("\x00" in argument for argument in command):
        raise ValueError("NUL is reserved as the argv separator")

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
    if not secret:
        raise ValueError("An approval secret is required")
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
    if not secret or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        return False
    try:
        expected_token = generate_approval_token(
            action_id=action_id,
            secret=secret,
            patch=patch,
            command=command,
        )
        return hmac.compare_digest(token, expected_token)
    except (ValueError, TypeError):
        return False
