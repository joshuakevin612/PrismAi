# Member 2 handoff: frontend and API integration

Branch: `member-3-frontend`, based on your `member-2-backend` commit `70f7d3d4b3abb1114053b07e3cb272a868c5ce3d`.

## What Member 3 delivered

- React/TypeScript frontend in `frontend/`: context selection, task polling, analysis, screenshot, patch and argv review, approval/rejection, cancellation, and execution results.
- Network and non-JSON error recovery, retryable error controls, disabled approval for `policy_ok=false`, and polling stopped in terminal states.
- Generated `frontend/src/api/types.ts` from your actual FastAPI OpenAPI; no handwritten duplicate API models.
- Five TaskView fixtures, frontend tests, and an AJV endpoint contract runner.
- Browser demo independent of the backend. Turn Demo mode off to use your backend.

Your backend, perception placeholders, and `shared/schemas.py` are unchanged by this branch. The previous backend README is preserved at `docs/BACKEND_README.md`.

## Get and run

```powershell
git fetch origin
git switch --track origin/member-3-frontend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci --prefix frontend
```

If the local branch already exists, use `git switch member-3-frontend` instead. Run these commands from the repository root.

Terminal 1:

```powershell
$env:MOCK_MODE='1'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
npm run dev --prefix frontend
```

Open http://127.0.0.1:5173 and turn **Demo mode off**. The backend still uses simulated perception and execution at this checkpoint. Keep the backend working directory at the repository root so its mock screenshot path resolves.

## Checks to run

Use an idle backend; the runner creates and cancels disposable tasks and rejects proposals. It does not approve an allowed action.

```powershell
$env:API_BASE_URL='http://127.0.0.1:8000/api'
npm run test:integration --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
$env:MOCK_MODE='1'
.\.venv\Scripts\python.exe -m pytest -q
```

Before this handoff, 8 frontend tests, 21 backend tests, the production build, and the endpoint/mock drill runner passed. Browser testing also verified backend submission, screenshot/context display, proposal review, and approval through simulated completion.

`test:integration` checks all six endpoint routes, response schemas, validation errors, concurrency, rejection, cancellation, policy denial, model timeout, invalid model output, context failure, and PNG signature. `test:contract` omits backend-specific drill commands. Real execution and hardware failure drills are still pending.

## What Member 3 needs from you next

1. Integrate Member 1's real collection and sandbox implementation. In particular, your current sandbox calls include `secret=` and `allowed_root=` kwargs; agree on that signature with M1 before replacing the placeholder.
2. Configure and verify the real model with backend-only environment values. Return model failures as `TaskView.error` with the agreed retryability.
3. Keep proposal policy validation and the explicit decision gate intact. Confirm cancellation behavior during real collection, model calls, and execution.
4. Supply a disposable `ALLOWED_ROOT` and a repeatable real approval/execution example for final UI verification.
5. Notify M3 of schema changes. Changes to shared models go through the agreed team review.

After changing schemas, regenerate from the Python source:

```powershell
.\.venv\Scripts\python.exe scripts/sync-backend-contract.py
npm run generate:types --prefix frontend
npm run build --prefix frontend
```

Alternatively, with the backend running, `npm run generate:types:live --prefix frontend` generates the TS types directly. The sync helper additionally exports the error envelope from `ErrorResponse`: your current OpenAPI does not declare that model in route error responses. Please add explicit error response models when updating API documentation, without changing the actual envelope.

## Merge boundary

Merge the Member 3 branch into the team's selected integration branch. Do not replace your backend with another copy: this branch already includes your base commit. M3's additions are `frontend/`, the handoff/design docs, schema snapshots and fixtures, helper scripts, and README/gitignore updates.
