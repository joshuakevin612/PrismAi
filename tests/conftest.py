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


@pytest.fixture(autouse=True)
def reset_task_manager():
    """Resets task manager state between tests."""
    task_manager.tasks.clear()
    task_manager.context_bundles.clear()
    task_manager.background_jobs.clear()
    yield


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        yield client
