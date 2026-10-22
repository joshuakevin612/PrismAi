# Member 1 handoff: perception and sandbox integration

Member 3's frontend is on `member-3-frontend`. It already works with Member 2's mock backend. You do not need to implement frontend code or expose a separate browser API.

## What you receive

- A UI for selecting screen, terminal, processes, and an optional GitHub PR.
- Captured screenshot/OCR, terminal error, PR file, and warning displays.
- A proposal reviewer showing the exact patch, argv arrays, risk, and policy denial reason.
- Explicit approval/rejection and cancellation controls, plus action stdout/stderr, exit status, duration, and denial reason.
- An endpoint contract runner for M2 integration. See `HANDOFF_MEMBER_2.md` for full local setup.

## What we need from you

Deliver your real `perception/` implementation to Member 2 through your branch/PR:

1. `collect_context(ContextRequest) -> ContextBundle`: respect the selected sources; return within 8 seconds; return partial results and warning codes for expected failures. Redact OCR, terminal excerpts, and process command lines before they leave your module.
2. `health() -> dict[str, bool]`: report actual component availability rather than canned success.
3. Screenshot output: return a backend-readable local PNG path when available. Member 2 serves that file through `/api/tasks/{id}/screenshot`; the browser never reads your filesystem path directly. Coordinate cleanup/lifetime with M2.
4. `validate_action`: inspect each proposed patch or argv command without executing it; return an explanatory denial code.
5. `execute`: validate the approval token, enforce resolved paths within `ALLOWED_ROOT`, enforce the command policy and network restrictions, apply approved patches/run approved commands, and return `ActionResult` for success, denial, failure, or timeout.

The existing `perception/sandbox.py` on M2's branch only returns simulated success; real sandbox execution is still required. An executable-name allowlist alone does not confine scripts launched by Python, Node, npm, or Git. Implement and test the promised restrictions at the execution boundary.

## Coordinate these details with Member 2

- M2 currently calls `validate_action(..., allowed_root=...)` and `execute(..., secret=..., allowed_root=...)`. The pasted contract used one positional request argument; agree on compatibility before replacing the stub.
- Use M2's actual implementation in `backend/security.py` as the current token interoperability reference. Its hash includes payload-kind prefixes and, for patches, both path and diff. The shortened README formula is not the complete byte serialization. Agree on a shared implementation or test vectors.
- Keep `APPROVAL_SECRET` and `GITHUB_TOKEN` in the backend environment. M3 does not need their values.
- Agree on working-directory resolution, patch application, timeouts, output limits/redaction, and cancellation of running child processes.
- Request shared schema changes through the team's agreed review; M2 owns `shared/schemas.py`.

## Give the team these deliverables

- Your branch/PR and setup instructions, including Tesseract installation/path configuration.
- Required environment variable names, plus a disposable allowed-root setup and a harmless reproducible task. Do not send secrets in the handoff.
- Sample successful and partial ContextBundle results, with representative warning codes.
- Tests/results for missing Tesseract, GitHub rate limiting, token verification, command denial, and real patch/command execution.
- Reproduction steps and expected denial codes for path traversal, a patch outside `ALLOWED_ROOT`, `rm -rf`, shell metacharacters, missing/forged approval tokens, and an attempted network call.

M3 will use those cases for the UI demo. All six security cases need to be exercised against the real implementation; passing the current mock tests does not verify isolation.

## Joint acceptance check

Once M2 integrates your module, start the backend from the repository root and the frontend on port 5173. Turn browser Demo mode off. Together verify real context and screenshots, partial warnings, policy-denied approval disabled, rejection with no execution, approval executing only the reviewed action, cancellation, and accurate action results. M3's generic endpoint smoke test is `npm run test:contract --prefix frontend`; use the mock-specific `test:integration` runner only with M2's mock mode enabled.
