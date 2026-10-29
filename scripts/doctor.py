"""Check local prerequisites without capturing context or printing credentials."""
import argparse
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-ocr', action='store_true')
    args = parser.parse_args()
    from backend.config import settings, APP_ROOT
    from backend.local_auth import require_loopback
    from shared.paths import safe_workspace
    from perception.container_runtime import availability
    from perception.screen import is_tesseract_available
    issue = None
    try:
        require_loopback(settings.HOST)
        safe_workspace(Path(settings.ALLOWED_ROOT), check_files=True)
    except (ValueError, OSError) as exc:
        issue = str(exc) if isinstance(exc, ValueError) else 'WORKSPACE_UNAVAILABLE'
    ok, reason = availability()
    result = {'nvidia_key_configured': bool(settings.NVIDIA_API_KEY.strip()),
        'model': settings.NEMOTRON_MODEL, 'workspace_safe': issue is None,
        'workspace_issue': issue, 'isolated_commands_ready': ok, 'isolation_reason': reason,
        'frontend_built': (APP_ROOT / 'frontend/dist/index.html').is_file(),
        'tesseract_ready': is_tesseract_available()}
    print(json.dumps(result, indent=2))
    return 0 if all([result['nvidia_key_configured'], result['workspace_safe'], ok,
                     result['frontend_built'], not args.require_ocr or result['tesseract_ready']]) else 1


if __name__ == '__main__':
    raise SystemExit(main())
