# PrismAi

An approval-gated developer assistant. Member 1 owns perception and sandbox execution, Member 2 owns the backend orchestrator and shared schemas, and Member 3 owns the frontend and endpoint contract checks.

This branch adds Member 3's frontend to Member 2's backend at commit `70f7d3d`. The current perception and sandbox modules simulate collection/execution. Real model and sandbox integration remain team checkpoints.

## Local setup

Requires Python 3.11+ and Node.js 22.12+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci --prefix frontend
```

Start the backend from the repository root:

```powershell
$env:MOCK_MODE='1'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
npm run dev --prefix frontend
```

Open http://127.0.0.1:5173. Demo mode starts enabled and uses an independent in-browser simulation. Turn it off to connect to the backend through Vite's `/api` proxy. The backend mock also simulates perception and execution; switching off browser Demo mode does not enable real hardware or real execution.

Public frontend defaults are documented in `frontend/.env.example`. Backend configuration is documented in the root `.env.example`; backend secrets must never use the `VITE_` prefix.

## Verification

With an idle backend running in mock mode:

```powershell
$env:API_BASE_URL='http://127.0.0.1:8000/api'
npm run test:integration --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
$env:MOCK_MODE='1'
.\.venv\Scripts\python.exe -m pytest -q
```

The frontend's eight tests cover fixture schemas, request failures, and mock state/approval behavior. The integration runner exercises all six endpoint routes, response shapes, concurrency, rejection, cancellation, policy denial, model/context failure drills, and PNG screenshots. It does not approve an allowed proposal. Member 2's 21 backend tests cover the simulated approval/execution path as well.

For an API-compatible backend without M2's mock drill commands, use `npm run test:contract --prefix frontend`. Real collection, sandbox execution, cancellation of real child processes, and hardware/security drills still need joint verification.

## Shared types

`shared/schemas.py` remains owned by Member 2. TypeScript models are generated, not maintained by hand:

```powershell
.\.venv\Scripts\python.exe scripts/sync-backend-contract.py
npm run generate:types --prefix frontend
```

The sync helper exports `fixtures/openapi.json` from FastAPI and `fixtures/error-response.schema.json` from the Python ErrorResponse model. The latter is separate because the backend currently omits it from route OpenAPI response declarations. With a backend running, `npm run generate:types:live --prefix frontend` generates TypeScript directly from `/openapi.json`.

## Team handoffs

- [Member 2: setup, API checks, schema workflow, and remaining backend integration](HANDOFF_MEMBER_2.md)
- [Member 1: perception/sandbox requirements, interoperability, and security demo cases](HANDOFF_MEMBER_1.md)
- [Original Member 2 backend documentation](docs/BACKEND_README.md)

Member 3's UI includes context selection, analysis and warning displays, screenshot retrieval, exact diff/argv review, policy-based approval controls, rejection/cancellation, and action output. Task history is limited to the current page session. API errors have explicit retry controls, and polling stops on terminal states.
