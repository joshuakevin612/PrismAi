"""Compatibility imports for the team's shared approval-token implementation."""
from shared.approval import (
    sign_action,
    verify_action,
    compute_action_payload_hash,
    generate_approval_token,
    verify_approval_token,
)

__all__ = ['sign_action', 'verify_action', 'compute_action_payload_hash', 'generate_approval_token', 'verify_approval_token']
