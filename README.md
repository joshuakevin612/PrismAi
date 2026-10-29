# Prism

A local developer assistant that selects relevant context, diagnoses issues with NVIDIA Nemotron, and proposes exact patches and Docker commands for your approval.

## Prerequisites

- Python 3.11 and Node.js 22.
- Docker Desktop using Linux containers (Windows), or Docker Engine (Linux).
- An NVIDIA API key and access to the configured model.
- Optional: Tesseract for screen text recognition.

## Setup

```powershell
git clone https://github.com/joshuakevin612/PrismAi.git
cd PrismAi
python -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes -r requirements-bootstrap.lock
.venv/Scripts/python.exe -m pip install --require-hashes -r requirements.lock
npm ci --prefix frontend
npm run build --prefix frontend
```

Only `.env.example` is included. Copy it to a private `.env` if you do not already have one, set `NVIDIA_API_KEY`, and replace the `APPROVAL_SECRET` placeholder with a private random value. Generate one locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Never commit the real `.env` or put credentials under `ALLOWED_ROOT`.

For the default example workspace:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
New-Item -ItemType Directory -Force demo-workspace
```

Edit `.env` before continuing. Keep `ALLOWED_ROOT=./demo-workspace`, or set it to an existing credential-free project directory. To create the optional bug-reproduction example, run `.venv/Scripts/python.exe scripts/prepare-demo.py` after configuration.

```powershell
docker build -t prism-sandbox:local sandbox
.venv/Scripts/python.exe scripts/doctor.py
.venv/Scripts/python.exe scripts/run_backend.py
```

The launcher opens the built UI on `http://127.0.0.1:8000` through a private pairing link. The frontend and API share one origin. A new process normally needs fresh browser pairing. Keep one backend process running; do not expose it to the network.

On Linux, use `.venv/bin/python` in place of `.venv/Scripts/python.exe`, `cp` in place of `Copy-Item`, and `mkdir -p demo-workspace` in place of `New-Item`.

## Frontend development

Run `npm run dev --prefix frontend` in one terminal and `.venv/Scripts/python.exe scripts/run_backend.py --dev` in another. Use the default backend address `127.0.0.1:8000`; the launcher pairs the same-host Vite frontend on port 5173. The UI source, fonts, sprites, and interactions are preserved.

## Permissions and privacy

Every proposed action needs approval. File modification, dependency installation, and command networking ask first by default. Screen, terminal, and process sources are initially available automatically; switches revoke automatic access. Saved access settings remain authoritative. Credentials and known sensitive-file paths cannot be collected or patched; command mounts reject known credential files, links, and unsafe roots. Arbitrary approved programs with a write/network grant have broad capabilities inside the allowed workspace.

NVIDIA receives the selected redacted text; attached PRs use GitHub's API. Screenshots remain local and their pixels are not redacted. Command-network permission is separate from these configured APIs. See [privacy and retention](docs/PRIVACY.md) and the [runbook](docs/RUNBOOK.md).

## Checks

```powershell
.venv/Scripts/python.exe -m pip install --require-hashes -r requirements-tools.lock
.venv/Scripts/python.exe scripts/check.py --docker --security
```

Add `--ocr` when Tesseract is installed. Checks start their own isolated authenticated backend and send no real workstation context or live model requests. The optional `scripts/model_smoke.py` uses synthetic text to verify the real provider and may consume provider quota.

The repository includes only application source/assets, locked setup/build inputs, example configuration, required tests/fixtures, dependency notices, and CI/release tooling. Generated builds, virtual environments, installed packages, local state, screenshots, audit evidence, reference checkouts, and real credentials are excluded.

See [setup details](docs/LIVE_SETUP.md), [API contract](docs/INTEGRATION_CONTRACT.md), [release/rollback instructions](docs/RELEASING.md), and [perception integration](docs/MEMBER_1_INTEGRATION.md).
