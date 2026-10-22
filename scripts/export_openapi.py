"""scripts/export_openapi.py - Generates and saves openapi.json to disk."""

import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.main import app

def export_openapi():
    spec = app.openapi()
    output_path = project_root / "openapi.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    print(f"Exported OpenAPI spec to {output_path.resolve()}")

if __name__ == "__main__":
    export_openapi()
