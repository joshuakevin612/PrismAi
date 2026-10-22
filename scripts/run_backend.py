"""scripts/run_backend.py - Server runner for Member 2 FastAPI backend."""

import sys
from pathlib import Path
import uvicorn

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.config import settings

if __name__ == "__main__":
    print(f"Starting Remediation Engine Backend on {settings.HOST}:{settings.PORT}")
    print(f"MOCK_MODE={settings.MOCK_MODE}")
    print(f"OpenAPI Spec: http://localhost:{settings.PORT}/openapi.json")
    print(f"Interactive Docs: http://localhost:{settings.PORT}/docs")
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
