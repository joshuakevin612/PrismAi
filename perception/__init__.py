"""perception - Public API contract for Member 1 perception module.

Member 2 imports only these names:
- collect_context
- health
- sandbox (ActionRequest, ActionResult, execute, validate_action)
"""

import os
from shared.schemas import ContextBundle, ContextRequest
from perception.mock import collect_mock_context, health as mock_health
from perception import sandbox

__all__ = ["collect_context", "health", "sandbox"]


def collect_context(req: ContextRequest) -> ContextBundle:
    """Collects system context (screen, terminal errors, processes, PR diffs).
    
    Guarantees:
    - Returns within 8s and never raises (returns partial results + warnings).
    - All text redacted for secrets.
    """
    return collect_mock_context(req)


def health() -> dict[str, bool]:
    """Returns component health status: {'tesseract': bool, 'github_token': bool, 'sandbox': bool}."""
    return mock_health()
