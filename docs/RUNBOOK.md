# Run, diagnose, and recover Prism

## Start and verify

Run `python scripts/run_backend.py` using the locked application environment. It serves the built frontend and `/api` together, listens only on loopback, opens a private pairing link, and permits one process per state directory. If the browser is unpaired, close that attempt and relaunch Prism. A second instance cannot take over the first instance's state. Never work around this by exposing port 8000 publicly or disabling authentication.

`python scripts/doctor.py` exits nonzero if model configuration, workspace safety, Docker/image, or the built frontend is unavailable. Add `--require-ocr` when testing the full screen-text feature. A configured key is not proof of provider availability; `python scripts/model_smoke.py` makes two minimal real-provider requests using synthetic text and no workstation context. It may consume provider quota.

If a request fails, note its `X-Request-ID`, application version, task ID, and error code. Inspect `STATE_DIR/logs/prism.log` locally. Do not share `.env`, `config.env`, pairing fragments, raw screenshots, or unreviewed logs. Revoking context cannot recall text already sent to NVIDIA.

## Common failures

| Symptom | Action |
| --- | --- |
| UNAUTHORIZED / unpaired browser | Relaunch and use the browser address opened by the launcher. Restart invalidates the previous process's cookie. |
| INVALID_HOST / INVALID_ORIGIN | Use the configured loopback host/port. For Vite use `--dev` and the same host on port 5173. Do not broaden trusted origins. |
| Another process owns state | Stop the old instance gracefully with Ctrl+C. The OS releases the file lock when the owner exits; deleting a live lock file is not recovery. |
| WORKSPACE_CONTAINS_CREDENTIAL_FILES | Move credential files outside the allowed root. Use environment injection into the developer workflow rather than mounting secrets. Do not rename secrets merely to bypass detection. |
| WORKSPACE_LINK_NOT_ALLOWED / scan limit | Choose a smaller, self-contained working copy without links/junctions or credential-bearing dependencies. |
| Sandbox/image unavailable | Start Docker Linux containers; load the release's sandbox archive or build the development image. Installed releases select their recorded image digest, not a mutable tag. |
| Provider configuration error | Check the configured NVIDIA model, account access, and key privately. Model IDs and account entitlements can change. |
| Provider unavailable / timeout | Check connectivity/quota and retry; do not repeatedly send additional context to diagnose a transport failure. |
| TESSERACT_NOT_FOUND | Install/configure `TESSERACT_PATH`, or use terminal/process context and document the limited screen capability. |

## Reliability target

Local release target: authenticated API control operations (task reads, access decisions, cancel) should respond within two seconds for at least 99% of operations over a workday, excluding model inference and host Docker failures. A cancelled running command should be removed within 15 seconds. Use request duration/status logs and the real cancellation tests to investigate breaches. This is a product target, not a hosted uptime SLA.

If a release regresses security boundaries or this target repeatedly, stop promotion, preserve a redacted diagnostic record, and roll back. Record the trigger, affected version, user impact, mitigation, and a regression test before trying the next candidate.

## Rollback and workspace recovery

Stop Prism, then run `python scripts/release.py rollback --home <install-home>`. It verifies the previous installed code/asset hashes and runtime marker, then atomically switches the active version. Settings and `config.env` live outside version directories. Start with `python scripts/release.py run --home <install-home>`. The inactive release stays available for diagnosis; it is never overwritten.

Application rollback does not undo approved project writes. Before approving changes, use a disposable copy or a clean project commit/backup. If an approved sequence fails halfway, inspect `action_results`, identify the patches that succeeded, and restore only the affected files from that checkpoint. Re-run project tests before resuming. Never reset unrelated uncommitted work or automatically roll back completed writes during cancellation.

For persistent-state recovery, stop Prism and copy `config.env` and `state/access.json` to a private backup outside every command workspace. Restore those exact files only while Prism is stopped. On corrupt access JSON the backend disables automatic context rather than re-enabling revoked access. A fresh process requires fresh browser pairing after restoration.
