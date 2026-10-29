# Run and verify the integrated app

The project contains the frontend, backend, real perception, and isolated command runner. NVIDIA Build is the only model provider required.

## Local configuration

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-bootstrap.lock
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
npm ci --prefix frontend
npm run build --prefix frontend
```

Create `.env` from `.env.example` only if no local `.env` exists. Keep it at the
repository root, beside `README.md`. Put your key after `NVIDIA_API_KEY=`.
Use the exact `NEMOTRON_MODEL` ID shown on the NVIDIA Build model page.
The verified default is `nvidia/nemotron-3.5-lightning-30b-a3b`. The older
Nemotron 3 Super free endpoint is deprecated; a catalog listing alone does not
mean an endpoint is still usable.
Keep
`ALLOWED_ROOT=./demo-workspace` for initial verification; credentials belong
outside that directory. Generate a private random `APPROVAL_SECRET` locally.
No key is required in the browser, and `.env` must remain untracked. On a fresh clone, create the default workspace with `mkdir demo-workspace`, or configure an existing credential-free project directory.

NVIDIA's model catalog can list models that cannot be invoked by an account.
HTTP 401/403/404/422 is a non-retryable configuration error; confirm the model's
Try API example works in NVIDIA Build. HTTP 429, service failures, and timeouts
are retryable. No provider response bodies or keys are returned to the browser.

## Isolated command execution

Install and start Docker with Linux-container support (Docker Desktop on
Windows), then build the trusted runtime image once:

```powershell
docker build -t prism-sandbox:local sandbox
.\.venv\Scripts\python.exe scripts/doctor.py
```

The runner mounts only `ALLOWED_ROOT` at `/workspace`, does not forward backend
environment variables, disables command networking unless granted, drops capabilities, runs
as a non-root user, and limits memory, CPU, PIDs, output, and duration. The image
filesystem is read-only; scratch storage is a bounded temporary filesystem.
It never falls back to executing a model command on the host. The image contains
Python/pytest, Node/npm, and Git. Dependency installation asks for installation,
workspace modification, and network access before execution. Python installs use
`.prism/python` inside the allowed root; npm installs stay in the project.

Commands with forbidden binaries or shell metacharacters are denied during
proposal validation. Missing Docker/image also disables approval of proposals
containing commands. Patch-only proposals remain available.

Cancelling a command removes its entire container, including child processes.
Cancellation of a patch waits for the current atomic write and stops subsequent
actions; it does not undo a patch that already completed. Partial results remain
visible. Failed execution always leaves a terminal task error rather than a
task stuck in `executing`.

## Repeatable demonstration

```powershell
.\.venv\Scripts\python.exe scripts/prepare-demo.py
.\.venv\Scripts\python.exe scripts/run_backend.py
```

The launcher opens the paired, same-origin frontend on port 8000. For Vite development, stop the backend, run `npm run dev --prefix frontend` in another terminal, and use `python scripts/run_backend.py --dev`. Use the exact host opened by the launcher; its HTTP-only session cookie authenticates the proxied API. Prism automatically selects relevant context.
The demo helper writes a genuine KeyError traceback into the disposable
workspace without overwriting existing source files.

Suggested task: "Diagnose the captured KeyError. Propose a minimal patch to
app/main.py so missing prices count as zero. Use the exact workspace_files.
If isolated commands are unavailable, propose only the patch."

Check the exact diff before approving. The model supplies exact text replacements; the backend generates and
validates the unified diff before it is shown, so the model cannot guess hunk
coordinates. The existing unified-diff model response remains supported.
Approval must change only the reviewed
file, rejection must leave it unchanged, and cancellation must stop later actions.
If Docker is ready, include `["python", "-m", "pytest", "-q"]` as the verification
command. The command must complete inside the container and expose its real exit
code and redacted output.

## Perception and privacy

Terminal collection reads bounded tails of `terminal_stderr.log`, `error.log`,
and `.prism/terminal.log` inside `ALLOWED_ROOT`. It does not scrape an interactive
terminal buffer. Source files referenced by those errors are read only within
the allowed root, redacted, and bounded before being sent to the model.

Screen collection captures a local PNG. Tesseract is optional: configure its
binary using `TESSERACT_PATH`; when missing, the screenshot still works and OCR
returns a warning. Image pixels are not secret-redacted. OCR text, log excerpts,
process command lines, source context, and execution output are redacted.

Screenshots live in a unique session temp directory. The backend expires its
owned files after `SCREENSHOT_TTL_SECONDS` (default one hour), checks every 30
seconds, and cleans them on normal shutdown. It never recursively removes
unknown files. Abrupt process termination can leave OS temp files behind.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm test --prefix frontend
npm run build --prefix frontend
.\.venv\Scripts\python.exe scripts/check.py
```

The unified check command needs the locked developer tools (`requirements-tools.lock`), starts a disposable authenticated backend, and verifies the configuration-error path without sending real context. Native API clients require the process's `API_SESSION_TOKEN` as a Bearer credential; do not save that token in the workspace. Real Docker and OCR tests are
explicit opt-in checks; GitHub CI builds the image, installs Tesseract, and runs
them. Locally with prerequisites installed:

```powershell
$env:PRISM_RUN_DOCKER_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/test_container_live.py -q
```

The tests cover actual isolated execution, blocked network/host filesystem,
credential isolation, bounded/redacted output, timeout with child processes,
cancellation, approval/rejection, malformed tokens, real patch writes, provider
errors, and partial perception. Hardware-independent OCR tests use a synthetic
capture and the real Tesseract executable.

## Permission lifecycle

`GET /api/access` reads persistent backend settings; `POST /api/access` changes one capability. Context defaults to automatic availability. Writes, installs, and command networking default to asking. Disabled capabilities can be requested for one task through `POST /api/tasks/{id}/permissions/{request_id}` with `allow` or `deny`. A pending request survives popup dismissal and browser refresh while the backend stays running. Backend restart loses in-memory tasks and task grants; global settings remain in `.prism/access.json`.

A context-planning model call selects the minimum sources before collection. The analysis may ask for a second round of missing context. No screen, logs, or processes are collected until that source is authorized. Denying context continues with a warning. Approving an action snapshots it, then requests missing execution access. Denying execution access returns to review without executing. Global access changes never approve a proposal.

Revocation clears related captured context, removes task grants, and cancels a task already using that capability. During execution, cancellation removes the command container and waits for cleanup. An atomic patch already in progress can complete; revocation does not roll back completed writes. HMAC v2 binds the action payload, directory, and access flags, so a token cannot be reused with broader permissions.

The installation toggle controls explicit package-manager actions. A user-approved arbitrary program with both file and network access can also download/write files; those capabilities are broad permissions. Keep `ALLOWED_ROOT` limited to the intended project.
