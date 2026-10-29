"""Fixed interoperability vectors for every member's approval implementation."""
import pytest
from backend import security
from shared import approval
from shared.schemas import PatchFile


@pytest.mark.parametrize("payload,digest,token", [
    ({"command": ["python", "-m", "pytest"]},
     "36d64bfc0a8d2a2f5a7c989c82f870521acb092f2e9ff679e535277e0c2b8e5a",
     "48730215f2e636d06c8d67105d56b9d3ac62feb5fbd4ded74368222a98e2369f"),
    ({"patch": PatchFile(path="demo.txt", unified_diff="--- a/demo.txt\n+++ b/demo.txt\n@@ -1 +1 @@\n-before\n+after\n")},
     "69ec365b66718ca6bad66e38876b84adb9c40826cdc1b3353e1e1c97550657f0",
     "a9e4e307bda7ece01aa784bd460c32efdafef5ba995be032d37361b3962ceb63"),
])
def test_m2_v1_interoperability_vectors(payload, digest, token):
    assert approval.compute_action_payload_hash(**payload) == digest
    assert security.generate_approval_token("act-vector", secret="team-contract-test", **payload) == token
    assert approval.verify_approval_token(token, "act-vector", secret="team-contract-test", **payload)
    assert security.generate_approval_token is approval.generate_approval_token


def test_argv_boundaries_are_bound_to_token():
    token = approval.generate_approval_token("action", secret="test", command=["python", "a b"])
    assert not approval.verify_approval_token(token, "action", secret="test", command=["python", "a", "b"])


@pytest.mark.parametrize("token", ["", "forged", "é" * 64, "z" * 64])
def test_malformed_tokens_are_denials(token):
    assert not approval.verify_approval_token(token, "action", secret="test", command=["python"])


def test_ambiguous_payload_and_nul_are_rejected():
    with pytest.raises(ValueError):
        approval.generate_approval_token("action", secret="test")
    with pytest.raises(ValueError):
        approval.generate_approval_token("action", secret="", command=["python"])
    with pytest.raises(ValueError):
        approval.generate_approval_token("action", secret="test", command=["python"], patch=PatchFile(path="x", unified_diff="x"))
    with pytest.raises(ValueError):
        approval.generate_approval_token("action", secret="test", command=["python", "a\x00b"])


def test_sandbox_requires_explicit_backend_configuration():
    from perception.sandbox import execute, validate_action
    from shared.schemas import ActionRequest
    request = ActionRequest(action_id="a", kind="run_command", command=["python"], working_dir=".", approval_token="")
    with pytest.raises(TypeError):
        validate_action(request)
    with pytest.raises(TypeError):
        execute(request, allowed_root=".")


def test_dry_run_rejects_mixed_payload_and_nul():
    from perception.sandbox import validate_action
    from shared.schemas import ActionRequest
    request = ActionRequest(action_id="a", kind="run_command", command=["python"],
                            patch=PatchFile(path="x", unified_diff="x"),
                            working_dir=".", approval_token="")
    assert validate_action(request, allowed_root=".") == (False, "ACTION_PAYLOAD_MISMATCH")
    request.patch = None
    request.command = ["python", "a\x00b"]
    assert validate_action(request, allowed_root=".") == (False, "INVALID_COMMAND_ARGUMENT")
