"""
perception package
Public API surface for Member 1 (Perception & Secure Sandbox).
"""

import os
from pathlib import Path

from shared.schemas import ContextBundle, ContextRequest
from perception.screen import is_tesseract_available
from perception.github import is_github_configured
from perception.sandbox import get_allowed_root
from perception import sandbox


def collect_context(req: ContextRequest) -> ContextBundle:
    """Collects system context (screen, terminal errors, processes, PR diffs).
    
    In MOCK_MODE (default during integration & UI testing), returns canned realistic bundle.
    In LIVE mode, runs concurrent collection across screen OCR, terminal logs, and GitHub.
    """
    if os.getenv("MOCK_MODE", "1") == "1":
        from perception.mock import collect_context as mock_collect
        return mock_collect(req)

    from perception.collector import collect_context as real_collect
    return real_collect(req)


def health() -> dict[str, bool]:
    """
    Returns health status of perception dependencies:
    {'tesseract': True, 'github_token': True, 'sandbox': True}
    """
    if os.getenv("MOCK_MODE", "1") == "1":
        from perception.mock import health as mock_health
        return mock_health()

    tesseract_ok = is_tesseract_available()
    github_ok = is_github_configured()
    sandbox_ok = False
    try:
        root_path = get_allowed_root()
        sandbox_ok = root_path.exists() and root_path.is_dir()
    except Exception:
        sandbox_ok = False

    return {
        "tesseract": tesseract_ok,
        "github_token": github_ok,
        "sandbox": sandbox_ok,
    }


__all__ = [
    "collect_context",
    "health",
    "sandbox",
]
