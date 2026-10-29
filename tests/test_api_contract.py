"""REST permissions and real execution boundary acceptance tests."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from backend.task_manager import task_manager
from backend.model_client import ContextPlan, SourceChoice, ModelClientException
from backend.config import settings
from shared.schemas import Analysis, Proposal, PatchFile
from tests.test_live_task_flow import poll

@pytest.fixture
def investigation(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'ALLOWED_ROOT', str(tmp_path))
    (tmp_path / 'app.py').write_text('before\n')
    analysis = Analysis(summary='Fix', root_cause='Incorrect value', explanation='Update value', confidence=.9,
        proposals=[Proposal(id='fix', title='Fix', rationale='Correct value', risk='low', policy_ok=True,
            files=[PatchFile(path='app.py', unified_diff='--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-before\n+after\n')])])
    monkeypatch.setattr(task_manager.model_client, 'analyze', AsyncMock(return_value=analysis))
    return tmp_path

async def create(client):
    response = await client.post('/api/tasks', json={'command':'Fix this issue'})
    assert response.status_code == 202
    return response.json()['task_id']

async def test_health_validation_concurrency_and_cancel(async_client, investigation):
    assert 'mock_mode' not in (await async_client.get('/api/health')).json()['m1']
    assert (await async_client.post('/api/tasks', json={'command':''})).status_code == 422
    tid = await create(async_client)
    assert (await async_client.post('/api/tasks', json={'command':'second'})).status_code == 409
    assert (await async_client.post(f'/api/tasks/{tid}/cancel')).json()['state'] == 'cancelled'
    assert (await async_client.post(f'/api/tasks/{tid}/cancel')).status_code == 409
    assert (await async_client.get('/api/tasks/missing')).status_code == 404

@pytest.mark.parametrize('decision', ['allow','deny'])
async def test_approved_patch_waits_for_access(async_client, investigation, decision):
    tid = await create(async_client)
    await poll(async_client, tid, {'awaiting_approval'})
    await async_client.post(f'/api/tasks/{tid}/decision', json={'proposal_id':'fix','decision':'approve'})
    task = await poll(async_client, tid, {'awaiting_permission'})
    request = task['permission_requests'][0]
    assert request['capabilities'] == ['modify_files']
    assert (investigation / 'app.py').read_text() == 'before\n'
    # Repeated polling/dismissal cannot resolve a backend request.
    assert (await async_client.get(f'/api/tasks/{tid}')).json()['state'] == 'awaiting_permission'
    path = f'/api/tasks/{tid}/permissions/{request["id"]}'
    assert (await async_client.post(path, json={'decision':decision})).status_code == 200
    assert (await async_client.post(path, json={'decision':decision})).status_code == 200
    assert (await async_client.post(path, json={'decision':'deny' if decision == 'allow' else 'allow'})).status_code == 409
    task = await poll(async_client, tid, {'completed' if decision == 'allow' else 'awaiting_approval'})
    assert (investigation / 'app.py').read_text() == ('after\n' if decision == 'allow' else 'before\n')
    assert (await async_client.get('/api/access')).json()['modify_files'] is False

@pytest.mark.parametrize('source', ['screen','terminal','processes'])
@pytest.mark.parametrize('decision', ['allow','deny'])
async def test_revoked_source_requires_specific_permission(async_client, investigation, monkeypatch, source, decision):
    from datetime import datetime, timezone
    from shared.schemas import ContextBundle
    import perception
    seen=[]
    def collect(req):
        seen.append(req)
        return ContextBundle(collected_at=datetime.now(timezone.utc))
    monkeypatch.setattr(perception, 'collect_context', collect)
    monkeypatch.setattr(task_manager.model_client, 'plan_context', AsyncMock(return_value=ContextPlan(sources=[SourceChoice(source=source, reason='Needed evidence')])))
    assert (await async_client.post('/api/access', json={'capability':source,'allowed':False})).status_code == 200
    tid = await create(async_client)
    task = await poll(async_client, tid, {'awaiting_permission'})
    assert not seen
    request = task['permission_requests'][0]
    assert request['capabilities'] == [source]
    await async_client.post(f'/api/tasks/{tid}/permissions/{request["id"]}', json={'decision':decision})
    await poll(async_client, tid, {'awaiting_approval'})
    assert getattr(seen[0], 'include_' + source) is (decision == 'allow')
    assert all(not getattr(seen[0], 'include_' + other) for other in {'screen','terminal','processes'} - {source})
    if decision == 'allow':
        revoked = await async_client.post('/api/access', json={'capability':source,'allowed':False})
        assert revoked.status_code == 200
        assert (await async_client.get(f'/api/tasks/{tid}')).json()['state'] == 'cancelled'

async def test_policy_denial_and_model_failure(async_client, investigation, monkeypatch):
    analysis = task_manager.model_client.analyze.return_value
    analysis.proposals[0].policy_ok = False
    tid = await create(async_client)
    await poll(async_client, tid, {'awaiting_approval'})
    assert (await async_client.post(f'/api/tasks/{tid}/decision', json={'proposal_id':'fix','decision':'approve'})).status_code == 422
    await async_client.post(f'/api/tasks/{tid}/decision', json={'proposal_id':'fix','decision':'reject'})
    monkeypatch.setattr(task_manager.model_client, 'plan_context', AsyncMock(side_effect=ModelClientException('MODEL_UNAVAILABLE','Unavailable',True)))
    tid = await create(async_client)
    task = await poll(async_client, tid, {'failed'})
    assert task['error']['code'] == 'MODEL_UNAVAILABLE'

async def test_no_proposals_completes(async_client, investigation):
    task_manager.model_client.analyze.return_value.proposals = []
    tid = await create(async_client)
    assert (await poll(async_client, tid, {'completed'}))['analysis']

async def test_access_validation(async_client):
    assert (await async_client.post('/api/access', json={'capability':'unknown','allowed':True})).status_code == 422
    assert (await async_client.get('/api/access')).json()['network'] is False

async def test_cancel_while_execution_permission_pending(async_client, investigation):
    tid = await create(async_client)
    await poll(async_client, tid, {'awaiting_approval'})
    await async_client.post(f'/api/tasks/{tid}/decision', json={'proposal_id':'fix','decision':'approve'})
    await poll(async_client, tid, {'awaiting_permission'})
    cancelled = await asyncio.wait_for(async_client.post(f'/api/tasks/{tid}/cancel'), 1)
    assert cancelled.json()['state'] == 'cancelled'
    assert not task_manager.has_active_task()
    assert (investigation / 'app.py').read_text() == 'before\n'

async def test_dependency_request_groups_permissions(async_client, investigation, monkeypatch):
    import perception.sandbox
    from shared.schemas import ActionResult
    proposal = task_manager.model_client.analyze.return_value.proposals[0]
    proposal.files = []
    proposal.commands = [['python','-m','pip','install','some-package']]
    monkeypatch.setattr(perception.sandbox, 'validate_action', lambda *a, **k: (True,None))
    executed=[]
    def execute(req, **kwargs):
        executed.append(req)
        return ActionResult(action_id=req.action_id,status='ok',duration_ms=1)
    monkeypatch.setattr(perception.sandbox, 'execute', execute)
    tid = await create(async_client)
    await poll(async_client, tid, {'awaiting_approval'})
    await async_client.post(f'/api/tasks/{tid}/decision', json={'proposal_id':'fix','decision':'approve'})
    task = await poll(async_client, tid, {'awaiting_permission'})
    req = task['permission_requests'][0]
    assert set(req['capabilities']) == {'modify_files','install_dependencies','network'}
    assert not executed
    await async_client.post(f'/api/tasks/{tid}/permissions/{req["id"]}',json={'decision':'allow'})
    await poll(async_client, tid, {'completed'})
    assert executed[0].access.model_dump() == {'modify_files':True,'install_dependencies':True,'network':True}


def test_access_settings_persist(tmp_path):
    from backend.permissions import PermissionStore
    path=tmp_path/'access.json'
    store=PermissionStore(path)
    store.update('screen', False)
    assert PermissionStore(path).settings.screen is False
    assert PermissionStore(path).settings.modify_files is False

async def test_enable_automatic_access_resumes_pending_request(async_client, investigation, monkeypatch):
    monkeypatch.setattr(task_manager.model_client,'plan_context',AsyncMock(return_value=ContextPlan(sources=[SourceChoice(source='terminal',reason='Need the traceback')])))
    await async_client.post('/api/access',json={'capability':'terminal','allowed':False})
    tid=await create(async_client)
    await poll(async_client,tid,{'awaiting_permission'})
    await async_client.post('/api/access',json={'capability':'terminal','allowed':True})
    task=await poll(async_client,tid,{'awaiting_approval'})
    assert task['permission_requests'][0]['status']=='allowed'
