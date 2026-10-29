# Perception integration

The frontend, orchestrator, and perception runner share `shared/schemas.py`. Context is selected automatically by the live model and authorized by the backend before collection. Tests inject fixtures; production always uses real collectors and sandbox execution.

Screen uses local capture and optional Tesseract. Terminal reads bounded project log tails. Processes use psutil. Explicit GitHub attachments use the GitHub API. Context failures produce partial warnings. See [setup and privacy](LIVE_SETUP.md).

Execution verifies the v2 signature over the exact payload, working directory and access flags. Patch targets remain inside ALLOWED_ROOT and must match the reviewed diff. Commands run only in Docker with permission-scoped file mounts and network. An access grant never overrides hard sandbox policy.

Run `python -m pytest -q` for contract, permission, patch, and provider tests. Set PRISM_RUN_DOCKER_TESTS=1 for actual container checks. Set PRISM_RUN_OCR_TESTS=1 with Tesseract installed for actual OCR checks.
