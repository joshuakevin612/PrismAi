"""backend/main.py - FastAPI application entrypoint with CORS, error envelope, and OpenAPI export."""

import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path
import secrets

from backend.config import settings, APP_ROOT
from backend.local_auth import LocalSessionMiddleware, authenticated, COOKIE, require_loopback, denied
from backend.router import router
from backend.task_manager import AppException, task_manager
from shared.schemas import ErrorResponse
from shared.version import VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app):
    from shared.paths import safe_workspace
    require_loopback(settings.HOST)
    safe_workspace(Path(settings.ALLOWED_ROOT))
    from perception.artifacts import screenshots
    from backend.runtime import instance_lock
    lock = instance_lock(Path(settings.STATE_DIR))
    lock.__enter__()
    screenshots.reopen()
    async def expire_screenshots():
        while True:
            await asyncio.sleep(30)
            await asyncio.to_thread(screenshots.cleanup, settings.SCREENSHOT_TTL_SECONDS)
            task_manager.prune_tasks()
    cleaner = asyncio.create_task(expire_screenshots())
    try:
        yield
    finally:
        cleaner.cancel()
        await asyncio.gather(cleaner, return_exceptions=True)
        await task_manager.shutdown()
        await asyncio.to_thread(screenshots.cleanup, close=True)
        lock.__exit__(None, None, None)

app = FastAPI(
    lifespan=lifespan,
    title="Autonomous Debugger & Remediation Engine API",
    description="Member 2 backend orchestrator bridging Member 1 (Perception) and Member 3 (UI).",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS configuration allowing Member 3 frontend
cors_origins = [f'http://{host}:{port}' for host in ('localhost', '127.0.0.1', '[::1]')
                for port in ({settings.PORT, 5173} if settings.DEV_FRONTEND else {settings.PORT})]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LocalSessionMiddleware)
from perception.redactor import register_secret
register_secret(settings.API_SESSION_TOKEN)


# ---------------------------------------------------------------------------
# Error Envelope Handlers (All non-2xx responses return standard JSON format)
# ---------------------------------------------------------------------------

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Formats 422 validation errors into contract error envelope."""
    # Build clean human-readable error summary
    errors = exc.errors()
    msg = "; ".join(f"{'.'.join(str(loc) for loc in err.get('loc', []))}: {err.get('msg')}" for err in errors)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Request body validation failed: {msg}",
                "retryable": False,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = "INTERNAL"
    if exc.status_code == 404:
        code = "TASK_NOT_FOUND"
    elif exc.status_code == 409:
        code = "INVALID_STATE"
    elif exc.status_code == 422:
        code = "VALIDATION_ERROR"
    elif exc.status_code == 502:
        code = "MODEL_UNAVAILABLE"
    elif exc.status_code == 405:
        code = "METHOD_NOT_ALLOWED"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": str(exc.detail),
                "retryable": exc.status_code == 502,
            }
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logging.getLogger("backend.main").exception("Unhandled exception")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL",
                "message": "An internal error occurred. Check the backend logs.",
                "retryable": False,
            }
        },
    )


# Include API routes under prefix /api
app.include_router(router)

from fastapi.openapi.utils import get_openapi

def session_openapi():
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        schema['components']['securitySchemes'] = {
            'LocalSession': {'type': 'apiKey', 'in': 'cookie', 'name': COOKIE},
            'LocalBearer': {'type': 'http', 'scheme': 'bearer'},
        }
        schema['security'] = [{'LocalSession': []}, {'LocalBearer': []}]
        app.openapi_schema = schema
    return app.openapi_schema

app.openapi = session_openapi


# Also expose openapi.json under /api/openapi.json in case frontend requests it with prefix
@app.get("/api/openapi.json", include_in_schema=False)
async def get_api_openapi_json():
    return app.openapi()


@app.post('/api/session', include_in_schema=False)
async def pair(request: Request):
    if not authenticated(request):
        return denied('UNAUTHORIZED', 'Invalid local pairing credential.', 401)
    response = Response(status_code=204)
    response.set_cookie(COOKIE, settings.API_SESSION_TOKEN, httponly=True, samesite='strict', path='/')
    return response


@app.get('/', include_in_schema=False)
async def root(request: Request):
    if not authenticated(request):
        nonce = secrets.token_urlsafe(24)
        # The fragment never reaches the server or access logs. Remove it from
        # browser history before exchanging it for an HTTP-only session cookie.
        html = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Prism</title>
<body><p id="message">Open Prism using scripts/run_backend.py to pair this browser.</p>
<script nonce="NONCE">(async()=>{const token=location.hash.slice(1);history.replaceState(null,'','/');
if(!token)return;try{const result=await fetch('/api/session',{method:'POST',headers:{Authorization:'Bearer '+token}});
if(!result.ok)throw Error();location.replace('/');}catch{document.getElementById('message').textContent='Pairing failed. Relaunch Prism to try again.';}})();</script></body></html>'''
        return HTMLResponse(html.replace('NONCE', nonce), headers={'Content-Security-Policy': f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
    if settings.DEV_FRONTEND:
        host = request.url.hostname
        return RedirectResponse(f'http://{host if host != "::1" else "[::1]"}:5173/', status_code=303)
    index = APP_ROOT / 'frontend' / 'dist' / 'index.html'
    if not index.is_file():
        return denied('FRONTEND_NOT_BUILT', 'Run npm ci --prefix frontend and npm run build --prefix frontend.', 503)
    return FileResponse(index, media_type='text/html')


@app.get('/{asset_path:path}', include_in_schema=False)
async def frontend_asset(asset_path: str):
    root = (APP_ROOT / 'frontend' / 'dist').resolve()
    path = (root / asset_path).resolve()
    if path.is_relative_to(root) and path.is_file() and not asset_path.startswith(('api/', '.')):
        return FileResponse(path)
    raise HTTPException(404, 'Not Found')
