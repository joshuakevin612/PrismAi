"""Launch one paired, loopback-only Prism instance without printing its token."""
import argparse
import os
from pathlib import Path
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='For automated clients supplying API_SESSION_TOKEN.')
    parser.add_argument('--dev', action='store_true', help='Pair the same-host Vite frontend on port 5173.')
    args = parser.parse_args()
    if args.dev:
        os.environ['DEV_FRONTEND'] = 'true'
    from backend.config import settings
    from backend.local_auth import require_loopback
    from backend.runtime import configure_logs
    from shared.paths import safe_workspace
    require_loopback(settings.HOST)
    safe_workspace(Path(settings.ALLOWED_ROOT))
    if not args.dev and not (ROOT / 'frontend/dist/index.html').is_file():
        parser.error('Build frontend first: npm ci --prefix frontend, then npm run build --prefix frontend')
    configure_logs(Path(settings.STATE_DIR))
    from backend.main import app
    import uvicorn
    host = f'[{settings.HOST}]' if ':' in settings.HOST else settings.HOST
    url = f'http://{host}:{settings.PORT}/'
    server = uvicorn.Server(uvicorn.Config(app, host=settings.HOST, port=settings.PORT,
                                         workers=1, access_log=False, log_config=None))
    if not args.no_browser:
        def pair_browser():
            for _ in range(60):
                if server.should_exit:
                    return
                if server.started:
                    webbrowser.open(url + '#' + settings.API_SESSION_TOKEN)
                    return
                time.sleep(.25)
        threading.Thread(target=pair_browser, daemon=True).start()
    print(f'Prism: {url} (one local process; close with Ctrl+C)')
    server.run()


if __name__ == '__main__':
    main()
