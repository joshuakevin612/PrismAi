# Local data and operational limits

Prism runs as one loopback-only process for one local user. It is not a hosted multi-user service. The launcher pairs the browser using a random process-scoped credential; it is exchanged for an HTTP-only, SameSite Strict session cookie. Restarting Prism invalidates that session and requires pairing again. Do not share the pairing link or persist `API_SESSION_TOKEN` in project files.

The release serves the existing frontend and API from the same local address. In development, `--dev` explicitly permits the same-host Vite origin on port 5173. Use the address opened by the launcher; `localhost` and `127.0.0.1` are different cookie hosts.

## What leaves the machine

- NVIDIA receives the task text and selected, redacted OCR/log/process/source/PR text needed for analysis. Context planning sends the task text before collecting sources. Inference is an external service and requires internet access regardless of command-network permission. Provider account terms and retention controls apply.
- An attached GitHub pull request is fetched from GitHub using the configured token. GitHub receives the requested repository/PR identity and API authentication. No GitHub attachment is fetched without a task specifying it.
- Approved network-enabled commands receive broad network connectivity inside a per-action Docker network. This is not an internet-only allowlist: reachable LAN/host services and external destinations depend on Docker/firewall settings. Prism's API still requires its session credential, which is not forwarded into containers.
- Prism has no automatic analytics, external error tracker, or support upload. Review and redact any diagnostics before sharing them.

Pattern redaction reduces known credential exposure but cannot identify every secret or personal detail. Do not place confidential material in a selected screen, log, source file, or pull request unless you intend the selected text to be processed by the provider.

## Files and permissions

Screen, terminal, and process sources are available automatically on a new installation; disable any source that should ask first. Saved settings remain authoritative. Execution always needs approval of the exact proposal. File modification, dependency installs, and command networking ask first by default. Task grants are removed when completed task records are cleaned up and cannot authorize another task.

Known credential paths (environment variants, SSH/cloud credentials, private-key files, and package credentials) are excluded from source collection and patch proposals. Harmless `.env.example`, `.env.sample`, and `.env.template` files remain available. Commands mount the whole chosen workspace; they are refused when the prerequisite scan finds known credential paths, links/junctions, an unsafe root, or more than 100,000 entries. Keep **all** credentials outside the command workspace, including secrets in custom filenames that no filename scan can recognize. Git metadata is intentionally mounted for approved Git commands; never embed credentials in Git remote URLs/configuration.

Commands run in disposable Linux containers. A read grant exposes readable workspace files, even when the workspace is read-only. A write grant allows an approved arbitrary program to change files in that workspace; an installation toggle is not a universal package-install detector. Use a separate project copy for untrusted code. Cancel/revoke stops later actions and running command containers; a completed atomic patch is not automatically undone.

## Retention

- Text context/task history is kept in memory for up to `TASK_TTL_SECONDS` after the last task update (default one hour), plus the cleanup interval of at most 30 seconds. At most `MAX_RETAINED_TASKS` completed tasks are retained (default 100, enforced at cleanup/next task). Active tasks are not evicted while executing or waiting for a user decision; resolve or cancel them when finished.
- Screenshot PNGs are stored in a session-owned OS temporary directory and expire after `SCREENSHOT_TTL_SECONDS` (default one hour), plus the cleanup interval. Pixels are **not** redacted. Normal shutdown cleans owned screenshots; abrupt termination can leave OS temporary files.
- Restart loses in-memory tasks/history/grants. Access policy remains in `STATE_DIR/access.json`. Local logs rotate at 2 MB with three backups (about 8 MB total); they contain request IDs, status/timing/version, and redacted diagnostic messages, without request bodies or pairing links.
- The browser stores the last task ID and theme locally. It does not store the model API key. The session cookie is process-scoped but remains in the browser until the browser session ends or it is replaced; a restarted server rejects the old value.
- Already displayed text, screenshots, and this-session history may remain in browser memory until the page is refreshed or closed. Server expiry cannot recall content already viewed or sent to a provider. Production response policy blocks automatic remote Markdown images/media to reduce tracking or context exfiltration through embedded URLs.

## Distribution

Supported baseline: Python 3.11, Node 22 for building the UI, and Docker Desktop with Linux containers on Windows x64 (or an equivalent Linux x64 Docker engine). An installed application includes the built UI and does not need Node on the host. Tesseract is optional: without it screenshots still exist, but screen text cannot be analyzed. Install/configure Tesseract to advertise OCR support.

Dependency notices are included in `frontend/THIRD_PARTY_NOTICES.txt` and `docs/THIRD_PARTY_PYTHON_NOTICES.txt`. The project owner must select the application's distribution license and support contact before publishing; this work does not invent a license or grant third-party rights. Review bundled visual assets and dependency terms as part of that decision.
