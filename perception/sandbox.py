"""Dispatch between the real sandbox and M1 live actions."""
from shared.schemas import ActionRequest, ActionResult


def _implementation():
    from perception import live_sandbox
    return live_sandbox


def validate_action(req: ActionRequest, *, allowed_root: str) -> tuple[bool, str | None]:
    """Inspect without side effects; the backend explicitly supplies its root."""
    if req.kind == "apply_patch" and (req.patch is None or req.command is not None):
        return False, "ACTION_PAYLOAD_MISMATCH"
    if req.kind == "run_command" and (req.patch is not None or not req.command):
        return False, "ACTION_PAYLOAD_MISMATCH"
    if req.command and any("\x00" in argument for argument in req.command):
        return False, "INVALID_COMMAND_ARGUMENT"
    return _implementation().validate_action(req, allowed_root=allowed_root)


def execute(req: ActionRequest, *, secret: str, allowed_root: str, cancel_event=None) -> ActionResult:
    """Execute only with the backend's explicit approval secret and root."""
    implementation = _implementation()
    return implementation.execute(req, secret=secret, allowed_root=allowed_root, cancel_event=cancel_event)
