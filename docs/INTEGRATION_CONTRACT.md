# Integrated contract

`shared/schemas.py` is authoritative. Generate API snapshots with `python scripts/sync-backend-contract.py`, then frontend types with `npm run generate:types --prefix frontend`.

Routes: `GET /api/health`, `POST /api/tasks`, `GET /api/tasks/{id}`, `POST /api/tasks/{id}/decision`, `POST /api/tasks/{id}/cancel`, `GET /api/tasks/{id}/screenshot`, `GET /api/access`, `POST /api/access`, and `POST /api/tasks/{id}/permissions/{request_id}`. Errors use the shared ErrorResponse envelope.

Every API route and screenshot requires a paired HTTP-only session cookie or `Authorization: Bearer <API_SESSION_TOKEN>`. The launcher pairs via a process-scoped random fragment and `POST /api/session`; a new process invalidates old sessions. Cookie mutations require the exact trusted Origin. Host and Origin validation apply even to authenticated calls. Native clients must receive the token from their trusted parent process; the endpoint contract runner is provisioned by `scripts/check.py`. No token or credential is embedded in the UI bundle. Security requirements are declared in the generated OpenAPI snapshots; task and permission payload schemas remain unchanged.

Tasks progress through queued, planning_context, optional awaiting_permission, collecting_context, analyzing, awaiting_approval, optional awaiting_permission, executing, and a terminal state. Diagnosis with no actions completes directly. Only one active task is allowed. Poll TaskView for selected_sources, task_grants, permission_requests, current access, analysis and execution results.

AccessUpdate contains capability and allowed. Capabilities are screen, terminal, processes, modify_files, install_dependencies, network. Off means ask before use; allow grants one task and deny refuses the current request. Closing a popup sends no decision. A proposal approval is separate from access permission. The backend freezes the approved proposal and pauses until its required permissions are satisfied.

HMAC v2 covers the complete ActionRequest except its approval_token, including working_dir and ExecutionAccess. Live execution accepts only this token. The old v1 token helper is retained solely for compatibility vectors. Docker enforces read-only project mounts and disabled networking by default. All execution remains subject to hard path and command policy checks.

No browser or backend demo mode exists. Tests inject provider and collector fixtures inside pytest only; production has no magic task strings or simulated results.
