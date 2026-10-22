"""tests/test_api_contract.py - Tests all REST endpoints, state machine, and error envelopes."""

import asyncio
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(async_client: AsyncClient):
    res = await async_client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["schema_version"] == "1.0"
    assert data["backend"] is True
    assert "tesseract" in data["m1"]
    assert "sandbox" in data["m1"]


@pytest.mark.asyncio
async def test_create_task_validation_error(async_client: AsyncClient):
    # Empty command violates min_length=1
    res = await async_client.post("/api/tasks", json={"command": ""})
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_single_active_task_enforcement(async_client: AsyncClient):
    # Create first task
    res1 = await async_client.post("/api/tasks", json={"command": "pytest"})
    assert res1.status_code == 202
    task_id1 = res1.json()["task_id"]

    # Try creating second task while first is in progress
    res2 = await async_client.post("/api/tasks", json={"command": "npm test"})
    assert res2.status_code == 409
    data = res2.json()
    assert data["error"]["code"] == "TASK_IN_PROGRESS"


@pytest.mark.asyncio
async def test_task_state_machine_happy_path(async_client: AsyncClient):
    # 1. Create task
    res = await async_client.post("/api/tasks", json={"command": "pytest tests/test_payment.py"})
    assert res.status_code == 202
    task_id = res.json()["task_id"]

    # 2. Poll until awaiting_approval
    task_data = None
    for _ in range(10):
        await asyncio.sleep(0.5)
        poll_res = await async_client.get(f"/api/tasks/{task_id}")
        assert poll_res.status_code == 200
        task_data = poll_res.json()
        if task_data["state"] == "awaiting_approval":
            break

    assert task_data is not None
    assert task_data["state"] == "awaiting_approval"
    assert task_data["context"] is not None
    assert task_data["analysis"] is not None
    assert len(task_data["analysis"]["proposals"]) > 0

    proposal_id = task_data["analysis"]["proposals"][0]["id"]

    # 3. Approve proposal
    dec_res = await async_client.post(
        f"/api/tasks/{task_id}/decision",
        json={"proposal_id": proposal_id, "decision": "approve"},
    )
    assert dec_res.status_code == 200

    # 4. Poll until completed
    for _ in range(10):
        await asyncio.sleep(0.5)
        poll_res = await async_client.get(f"/api/tasks/{task_id}")
        task_data = poll_res.json()
        if task_data["state"] == "completed":
            break

    assert task_data["state"] == "completed"
    assert len(task_data["action_results"]) > 0
    assert task_data["action_results"][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_task_rejection(async_client: AsyncClient):
    # Create task
    res = await async_client.post("/api/tasks", json={"command": "pytest"})
    task_id = res.json()["task_id"]

    # Wait for awaiting_approval
    for _ in range(10):
        await asyncio.sleep(0.5)
        task_data = (await async_client.get(f"/api/tasks/{task_id}")).json()
        if task_data["state"] == "awaiting_approval":
            break

    proposal_id = task_data["analysis"]["proposals"][0]["id"]

    # Reject
    dec_res = await async_client.post(
        f"/api/tasks/{task_id}/decision",
        json={"proposal_id": proposal_id, "decision": "reject", "reason": "Not preferred"},
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["state"] == "rejected"


@pytest.mark.asyncio
async def test_policy_denied_approval_blocked(async_client: AsyncClient):
    # Trigger drill for policy denied proposal
    res = await async_client.post("/api/tasks", json={"command": "trigger-policy-denied"})
    task_id = res.json()["task_id"]

    for _ in range(10):
        await asyncio.sleep(0.5)
        task_data = (await async_client.get(f"/api/tasks/{task_id}")).json()
        if task_data["state"] == "awaiting_approval":
            break

    proposal = task_data["analysis"]["proposals"][0]
    assert proposal["policy_ok"] is False

    # Attempting to approve denied proposal must fail with 422 POLICY_DENIED
    dec_res = await async_client.post(
        f"/api/tasks/{task_id}/decision",
        json={"proposal_id": proposal["id"], "decision": "approve"},
    )
    assert dec_res.status_code == 422
    data = dec_res.json()
    assert data["error"]["code"] == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_cancellation(async_client: AsyncClient):
    res = await async_client.post("/api/tasks", json={"command": "pytest"})
    task_id = res.json()["task_id"]

    cancel_res = await async_client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["state"] == "cancelled"

    # Cancelling again returns 409 INVALID_STATE
    cancel_again = await async_client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel_again.status_code == 409
    assert cancel_again.json()["error"]["code"] == "INVALID_STATE"


@pytest.mark.asyncio
async def test_screenshot_endpoint(async_client: AsyncClient):
    res = await async_client.post("/api/tasks", json={"command": "pytest"})
    task_id = res.json()["task_id"]

    # Wait for collecting_context / awaiting_approval
    for _ in range(10):
        await asyncio.sleep(0.5)
        task_data = (await async_client.get(f"/api/tasks/{task_id}")).json()
        if task_data["context"] is not None:
            break

    # Get screenshot
    ss_res = await async_client.get(f"/api/tasks/{task_id}/screenshot")
    assert ss_res.status_code == 200
    assert ss_res.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_failure_drills(async_client: AsyncClient):
    # 1. Model unavailable (502 retryable)
    res1 = await async_client.post("/api/tasks", json={"command": "trigger-model-unavailable"})
    tid1 = res1.json()["task_id"]
    for _ in range(10):
        await asyncio.sleep(0.5)
        t = (await async_client.get(f"/api/tasks/{tid1}")).json()
        if t["state"] == "failed":
            break
    assert t["state"] == "failed"
    assert t["error"]["code"] == "MODEL_UNAVAILABLE"
    assert t["error"]["retryable"] is True

    # 2. Context failed
    res2 = await async_client.post("/api/tasks", json={"command": "trigger-context-fail"})
    tid2 = res2.json()["task_id"]
    for _ in range(10):
        await asyncio.sleep(0.5)
        t = (await async_client.get(f"/api/tasks/{tid2}")).json()
        if t["state"] == "failed":
            break
    assert t["state"] == "failed"
    assert t["error"]["code"] == "CONTEXT_FAILED"
