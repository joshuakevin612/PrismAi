"""backend/router.py - FastAPI routes implementing the M2 <-> M3 REST contract."""

import os
import asyncio
from pathlib import Path
from fastapi import APIRouter, Response, status
from fastapi.responses import FileResponse, JSONResponse

from shared.schemas import (
    CreateTaskRequest,
    DecisionRequest,
    HealthResponse,
    TaskCreatedResponse,
    TaskView,
    ErrorResponse,
)
from backend.task_manager import AppException, task_manager
import perception

router = APIRouter(prefix="/api", tags=["tasks"], responses={
    status: {"model": ErrorResponse} for status in [404, 409, 422, 500, 502]
})


@router.post(
    "/tasks",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskCreatedResponse,
    summary="Create a new analysis task",
)
async def create_task(req: CreateTaskRequest):
    """Creates a new task, returning 202 with task_id.
    
    Returns 409 TASK_IN_PROGRESS if another task is currently active.
    """
    task_id = await task_manager.create_task(req)
    return TaskCreatedResponse(schema_version="1.0", task_id=task_id)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskView,
    summary="Get full TaskView for polling",
)
async def get_task(task_id: str):
    """Returns the full TaskView. Polled by frontend every ~1 s."""
    return task_manager.get_task(task_id)


@router.post(
    "/tasks/{task_id}/decision",
    response_model=TaskView,
    summary="Submit user decision (approve / reject)",
)
async def submit_decision(task_id: str, req: DecisionRequest):
    """Submits approval or rejection of a proposal.
    
    Rules:
    - Only valid in awaiting_approval; otherwise 409 INVALID_STATE.
    - Approving a proposal with policy_ok=false returns 422 POLICY_DENIED.
    """
    return await task_manager.handle_decision(task_id, req)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskView,
    summary="Cancel a running task",
)
async def cancel_task(task_id: str):
    """Cancels a running non-terminal task."""
    return await task_manager.cancel_task(task_id)


@router.get(
    "/tasks/{task_id}/screenshot",
    summary="Get PNG screenshot of the captured screen",
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "PNG image of the captured screen",
        },
        404: {
            "model": ErrorResponse,
            "description": "Screenshot not found",
        },
    },
)
async def get_screenshot(task_id: str):
    """Serves the captured screen PNG (never inlined as base64 in TaskView)."""
    screenshot_path = task_manager.get_screenshot_path(task_id)
    if not screenshot_path or not Path(screenshot_path).exists():
        raise AppException(
            status_code=404,
            code="TASK_NOT_FOUND",
            message=f"No screenshot available for task '{task_id}'",
            retryable=False,
        )
    return FileResponse(screenshot_path, media_type="image/png")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Backend and M1 perception health status",
)
async def health():
    """Returns status of backend and M1 components (tesseract, github_token, sandbox)."""
    m1_health = await asyncio.to_thread(perception.health)
    from backend.config import settings
    m1_health['model_configured'] = bool(settings.NVIDIA_API_KEY.strip())
    return HealthResponse(
        schema_version="1.0",
        backend=True,
        m1=m1_health,
    )


from shared.schemas import AccessSettings, AccessUpdate, PermissionDecision
from backend.permissions import permission_store

@router.get('/access', response_model=AccessSettings)
async def get_access():
    return permission_store.settings

@router.post('/access', response_model=AccessSettings)
async def update_access(req: AccessUpdate):
    return await task_manager.update_access(req.capability, req.allowed)

@router.post('/tasks/{task_id}/permissions/{request_id}', response_model=TaskView)
async def permission_decision(task_id: str, request_id: str, req: PermissionDecision):
    return await task_manager.handle_permission(task_id, request_id, req.decision)
