"""backend/main.py - FastAPI application entrypoint with CORS, error envelope, and OpenAPI export."""

import logging
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.router import router
from backend.task_manager import AppException
from shared.schemas import ErrorResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Autonomous Debugger & Remediation Engine API",
    description="Member 2 backend orchestrator bridging Member 1 (Perception) and Member 3 (UI).",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS configuration allowing Member 3 frontend
cors_origins = [settings.CORS_ORIGIN, "http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = "INTERNAL"
    if exc.status_code == 404:
        code = "TASK_NOT_FOUND"
    elif exc.status_code == 409:
        code = "INVALID_STATE"
    elif exc.status_code == 422:
        code = "VALIDATION_ERROR"
    elif exc.status_code == 502:
        code = "MODEL_UNAVAILABLE"

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
                "message": f"Internal server error: {str(exc)}",
                "retryable": False,
            }
        },
    )


# Include API routes under prefix /api
app.include_router(router)


# Also expose openapi.json under /api/openapi.json in case frontend requests it with prefix
@app.get("/api/openapi.json", include_in_schema=False)
async def get_api_openapi_json():
    return app.openapi()


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "Remediation Engine Backend (Member 2)",
        "version": "1.0",
        "openapi": "/openapi.json",
        "api_docs": "/docs",
        "mock_mode": settings.MOCK_MODE,
    }
