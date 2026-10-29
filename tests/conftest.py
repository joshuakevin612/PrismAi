"""tests/conftest.py - Pytest fixtures and test environment setup."""

import sys
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.main import app
from backend.task_manager import task_manager
from backend.config import settings


@pytest_asyncio.fixture(autouse=True)
async def reset_task_manager():
    """Resets task manager state between tests."""
    task_manager.tasks.clear()
    task_manager.context_bundles.clear()
    task_manager.background_jobs.clear()
    task_manager.cancel_events.clear()
    task_manager.execution_jobs.clear()
    yield
    await task_manager.shutdown()


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000",
                           headers={'Authorization': 'Bearer ' + settings.API_SESSION_TOKEN}) as client:
        yield client

@pytest.fixture(autouse=True)
def isolate_access(monkeypatch):
    from backend.permissions import permission_store
    from shared.schemas import AccessSettings
    from backend.model_client import ContextPlan
    from unittest.mock import AsyncMock
    monkeypatch.setattr(permission_store, 'path', None)
    monkeypatch.setattr(permission_store, 'settings', AccessSettings())
    monkeypatch.setattr(task_manager.model_client, 'plan_context', AsyncMock(return_value=ContextPlan(sources=[])))
    task_manager.permission_events.clear()
    task_manager.used_capabilities.clear()
