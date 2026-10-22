# Autonomous Debugger & Remediation Engine — Backend (Member 2)

Member 2 is the orchestrator sitting at the center of the system:
- **M1 ↔ M2 Seam:** Perception & Sandbox execution (`perception/`)
- **M2 ↔ M3 Seam:** REST API & Polling State Machine (`http://localhost:8000/api`)
- **Model Contract:** Nebius / Nemotron context budgeting, prompt sanitization, JSON schema enforcement, and retry loops.
- **Single Source of Truth:** `shared/schemas.py` (Pydantic v2, `schema_version: "1.0"`).

---

## 1. Quickstart

### Prerequisites
- Python 3.11+
- Virtual environment

### Setup
```bash
# 1. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate       # Windows PowerShell
# source venv/bin/activate    # Linux / macOS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
```

### Running Tests
All 21 contract, security, context budgeting, and state machine tests:
```bash
pytest -v
```

### Starting the Backend
```bash
python scripts/run_backend.py
```
- **Base URL:** `http://localhost:8000/api`
- **OpenAPI Schema:** `http://localhost:8000/openapi.json`
- **Interactive Swagger UI:** `http://localhost:8000/docs`

---

## 2. Contracts & Integration Boundaries

### Ground Rules
1. **One Source of Truth:** `shared/schemas.py` owned by Member 2.
2. **Generated Types for Member 3:** M3 runs `openapi-typescript` against `openapi.json` to generate `frontend/src/api/types.ts`.
3. **Mocks First:** `MOCK_MODE=1` walks the full state machine with 1-second delays and simulates failure paths for M3 integration.
4. **Partial Results Over Exceptions:** M1 returns partial context + `warnings`, never raises.
5. **Schema Versioning:** Every top-level schema includes `schema_version: "1.0"`.

---

## 3. REST API (Member 2 → Member 3)

Base URL: `http://localhost:8000/api` (CORS enabled for `http://localhost:5173`).

### Task State Machine
```
queued → collecting_context → analyzing → awaiting_approval → executing → completed
                  ↓                ↓              ↓
                failed           failed        rejected
(any non-terminal state) → cancelled
```
*Terminal states:* `completed`, `rejected`, `failed`, `cancelled`. Member 3 stops polling on these.

### Endpoints

| Method | Path | Status | Purpose |
|---|---|---|---|
| `POST` | `/api/tasks` | `202 Accepted` | Submit task `{command, context}`. Returns `{task_id}`. |
| `GET` | `/api/tasks/{id}` | `200 OK` | Poll `TaskView` (polled every ~1 s). |
| `POST` | `/api/tasks/{id}/decision` | `200 OK` | Submit `{proposal_id, decision: "approve" \| "reject"}`. |
| `POST` | `/api/tasks/{id}/cancel` | `200 OK` | Cancel a running task. |
| `GET` | `/api/tasks/{id}/screenshot` | `200 OK` | Returns `image/png` (never inlined in `TaskView`). |
| `GET` | `/api/health` | `200 OK` | Backend + M1 component status. |

### Error Envelope
All non-2xx responses strictly conform to:
```json
{
  "error": {
    "code": "INVALID_STATE",
    "message": "Task is not awaiting approval",
    "retryable": false
  }
}
```

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Bad request body |
| `TASK_NOT_FOUND` | 404 | Unknown task id |
| `INVALID_STATE` | 409 | Action not allowed in current state |
| `TASK_IN_PROGRESS` | 409 | Another task is currently running (1 task at a time) |
| `POLICY_DENIED` | 422 | Proposal violates sandbox policy |
| `MODEL_UNAVAILABLE` | 502 | Nebius unreachable (retryable: true) |
| `MODEL_INVALID_RESPONSE` | 502 | Model output failed validation after 2 retries |
| `CONTEXT_FAILED` | 500 | M1 perception collection failed entirely |
| `INTERNAL` | 500 | Unhandled internal error |

---

## 4. Member 1 Boundary (Perception & Sandbox)

Member 1 delivers `perception/`:
- `collect_context(req: ContextRequest) -> ContextBundle`: returns within 8s, secret-redacted, partial results + `warnings`.
- `health() -> dict[str, bool]`: `{'tesseract': bool, 'github_token': bool, 'sandbox': bool}`.
- `sandbox.validate_action(req: ActionRequest) -> tuple[bool, Optional[str]]`: dry-run policy check without side-effects.
- `sandbox.execute(req: ActionRequest) -> ActionResult`: requires valid HMAC approval token signed with `APPROVAL_SECRET`.

### HMAC Approval Token Algorithm
```python
payload_hash = sha256(patch_content or "\0".join(command))
token = hmac_sha256(key=APPROVAL_SECRET, message=f"{action_id}:{payload_hash}")
```

---

## 5. Model Integration (Nebius / Nemotron)

1. **Context Budget:**
   - OCR text truncated to ~4k characters.
   - Unified diffs truncated to ~8k characters total.
   - Files mentioned in stack traces / terminal errors receive top priority.
   - `truncated: true` flags passed to prompt.
2. **Prompt Injection Defense:**
   - Screen and PR texts are passed as quoted JSON data blocks.
3. **Retry Loop:**
   - Model must output JSON conforming to `Analysis` (without `policy_ok`).
   - If output fails Pydantic validation, M2 retries up to 2 times with validation feedback.
   - If it still fails, marks task as `failed` with code `MODEL_INVALID_RESPONSE`.

---

## 6. Shared Fixtures (`fixtures/`)

| File | Description |
|---|---|
| `fixtures/successful_task.json` | Complete TaskView in `completed` state with actions and diff. |
| `fixtures/failed_task.json` | TaskView in `failed` state with retryable `MODEL_UNAVAILABLE`. |
| `fixtures/policy_denied_proposal.json` | TaskView in `awaiting_approval` with `policy_ok: false`. |
| `fixtures/model_invalid_response.json` | TaskView in `failed` state with non-retryable `MODEL_INVALID_RESPONSE`. |
| `fixtures/empty_context_with_warnings.json` | M1 `ContextBundle` with `warnings` for missing Tesseract/GitHub rate limit. |

---

## 7. M3 TypeScript Type Generation

Run the following command to update frontend types whenever schemas evolve:
```bash
# Export schema to disk
python scripts/export_openapi.py

# Generate TypeScript definitions in frontend
npx openapi-typescript openapi.json -o frontend/src/api/types.ts
```
