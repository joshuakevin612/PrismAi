"""Export M2's actual FastAPI OpenAPI and Pydantic error envelope, without editing M2."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
backend = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (root if (root / 'backend').is_dir() else root / 'member2-backend')
sys.path.insert(0, str(backend))
from backend.main import app
from shared.schemas import ErrorResponse

for name, value in [('openapi.json', app.openapi()), ('error-response.schema.json', ErrorResponse.model_json_schema())]:
    (root / 'fixtures' / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
(root / 'openapi.json').write_text(json.dumps(app.openapi(), indent=2) + '\n', encoding='utf-8')
print('Synced OpenAPI and error envelope directly from Member 2 Python models.')
