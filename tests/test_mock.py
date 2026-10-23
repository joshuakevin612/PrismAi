"""
tests/test_mock.py
Tests perception/mock.py against schemas to ensure Day 2 contract compliance.
"""

from shared.schemas import ContextRequest, ActionRequest
from perception import mock


def test_mock_collect_context():
    req = ContextRequest(
        include_screen=True,
        include_terminal=True,
        include_processes=True,
    )
    bundle = mock.collect_context(req)

    assert bundle.schema_version == "1.0"
    assert bundle.screen is not None
    assert len(bundle.terminal_errors) > 0
    assert len(bundle.processes) > 0
    assert bundle.terminal_errors[0].exception_type == "sqlalchemy.exc.NoResultFound"
    assert bundle.warnings == []


def test_mock_execute():
    req = ActionRequest(
        action_id="mock_act_1",
        kind="run_command",
        command=["python", "--version"],
        working_dir=".",
        approval_token="any-token",
    )
    res = mock.execute(req)

    assert res.action_id == "mock_act_1"
    assert res.status == "ok"
    assert res.exit_code == 0


def test_mock_health():
    h = mock.health()
    assert h == {"tesseract": True, "github_token": True, "sandbox": True}
