"""tests/test_schemas.py - Tests validation of shared schemas and fixtures."""

import json
from pathlib import Path
from shared.schemas import ContextBundle, TaskView


def test_successful_task_fixture():
    fixture_path = Path("fixtures/successful_task.json")
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    task = TaskView.model_validate(data)
    assert task.schema_version == "1.0"
    assert task.state == "completed"
    assert task.analysis is not None
    assert len(task.analysis.proposals) > 0
    assert task.analysis.proposals[0].policy_ok is True
    assert len(task.action_results) == 2


def test_failed_task_fixture():
    fixture_path = Path("fixtures/failed_task.json")
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    task = TaskView.model_validate(data)
    assert task.state == "failed"
    assert task.error is not None
    assert task.error.code == "MODEL_UNAVAILABLE"
    assert task.error.retryable is True


def test_policy_denied_fixture():
    fixture_path = Path("fixtures/policy_denied_proposal.json")
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    task = TaskView.model_validate(data)
    assert task.state == "awaiting_approval"
    assert task.analysis is not None
    assert task.analysis.proposals[0].policy_ok is False
    assert "COMMAND_NOT_ALLOWLISTED" in (task.analysis.proposals[0].policy_denial_reason or "")


def test_model_invalid_response_fixture():
    fixture_path = Path("fixtures/model_invalid_response.json")
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    task = TaskView.model_validate(data)
    assert task.state == "failed"
    assert task.error is not None
    assert task.error.code == "MODEL_INVALID_RESPONSE"
    assert task.error.retryable is False


def test_empty_context_with_warnings_fixture():
    fixture_path = Path("fixtures/empty_context_with_warnings.json")
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    bundle = ContextBundle.model_validate(data)
    assert bundle.schema_version == "1.0"
    assert len(bundle.warnings) == 2
    assert "TESSERACT_NOT_FOUND" in bundle.warnings
