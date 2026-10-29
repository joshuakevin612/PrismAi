"""Joint M1/M2 acceptance: real log collection and patch writes via REST."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from backend.config import settings
from backend.task_manager import task_manager
from shared.schemas import Analysis, Proposal, PatchFile, ActionResult


async def poll(client, task_id, states):
    for _ in range(150):
        task = (await client.get('/api/tasks/' + task_id)).json()
        if task['state'] in states:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError('Task did not reach expected state')


def plan():
    return Analysis(summary='Fix', root_cause='Missing price', explanation='Use zero', confidence=0.99,
        proposals=[Proposal(id='fix', title='Use default', rationale='Missing field', risk='low',
            files=[PatchFile(path='app.py', unified_diff='--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-before\n+after\n')],
            commands=[], policy_ok=True)])


@pytest.fixture
def live_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'ALLOWED_ROOT', str(tmp_path))
    monkeypatch.setattr(task_manager.model_client, 'analyze', AsyncMock(return_value=plan()))
    from backend.permissions import permission_store
    permission_store.update('modify_files', True)
    (tmp_path / 'app.py').write_text('before\n')
    (tmp_path / 'terminal_stderr.log').write_text('Traceback (most recent call last):\n  File "app.py", line 1, in run\n    before\nKeyError: price\n')
    return tmp_path


@pytest.mark.parametrize('decision', ['approve', 'reject'])
async def test_real_collection_and_patch_gate(live_workspace, async_client, decision):
    response = await async_client.post('/api/tasks', json={'command':'fix pricing', 'context':{'auto':False,'include_screen':False,'include_terminal':True}})
    task_id = response.json()['task_id']
    task = await poll(async_client, task_id, {'awaiting_approval'})
    assert task['context']['terminal_errors'][0]['exception_type'] == 'KeyError'
    assert (live_workspace / 'app.py').read_text() == 'before\n'
    response = await async_client.post(f'/api/tasks/{task_id}/decision', json={'proposal_id':'fix','decision':decision})
    assert response.status_code == 200
    task = await poll(async_client, task_id, {'completed','rejected','failed'})
    assert task['state'] == ('completed' if decision == 'approve' else 'rejected')
    assert (live_workspace / 'app.py').read_text() == ('after\n' if decision == 'approve' else 'before\n')
    if decision == 'approve':
        assert task['action_results'][0]['status'] == 'ok'


async def test_execution_exception_is_reported(live_workspace, async_client, monkeypatch):
    import perception.sandbox
    def broken(*args, **kwargs):
        raise OSError('simulated I/O failure')
    monkeypatch.setattr(perception.sandbox, 'execute', broken)
    task_id = (await async_client.post('/api/tasks', json={'command':'fix','context':{'auto':False,'include_screen':False,'include_terminal':False}})).json()['task_id']
    await poll(async_client, task_id, {'awaiting_approval'})
    await async_client.post(f'/api/tasks/{task_id}/decision', json={'proposal_id':'fix','decision':'approve'})
    task = await poll(async_client, task_id, {'failed'})
    assert task['error']['code'] == 'EXECUTION_FAILED'


async def test_cancel_execution_prevents_later_actions(live_workspace, async_client, monkeypatch):
    import perception.sandbox
    import threading
    entered = threading.Event()
    executed = []
    analysis = plan()
    analysis.proposals[0].files.append(PatchFile(path='second.py', unified_diff='@@ -0,0 +1 @@\n+untouched\n'))
    monkeypatch.setattr(task_manager.model_client, 'analyze', AsyncMock(return_value=analysis))
    def slow(req, *, secret, allowed_root, cancel_event):
        executed.append(req.action_id)
        entered.set()
        assert cancel_event.wait(3), 'Cancellation did not reach the executing action'
        return ActionResult(action_id=req.action_id,status='denied',denial_reason='ACTION_CANCELLED',duration_ms=1)
    monkeypatch.setattr(perception.sandbox, 'execute', slow)
    task_id = (await async_client.post('/api/tasks', json={'command':'fix','context':{'auto':False,'include_screen':False,'include_terminal':False}})).json()['task_id']
    await poll(async_client, task_id, {'awaiting_approval'})
    await async_client.post(f'/api/tasks/{task_id}/decision', json={'proposal_id':'fix','decision':'approve'})
    for _ in range(100):
        if entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert entered.is_set()
    cancelled = await async_client.post(f'/api/tasks/{task_id}/cancel')
    assert cancelled.json()['state'] == 'cancelled'
    assert len(executed) == 1 and not (live_workspace / 'second.py').exists()
