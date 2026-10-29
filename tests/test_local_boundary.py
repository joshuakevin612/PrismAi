"""Regression tests for the release audit's API and credential-file bypasses."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import httpx
import pytest

from backend.main import app
from backend.config import settings, APP_ROOT
from backend.local_auth import COOKIE, require_loopback
from backend.task_manager import task_manager
from backend.model_client import FileEditFromModel
from backend.workspace_context import read_workspace_files, materialize_edit
from backend.runtime import instance_lock
from shared.paths import safe_workspace
from shared.schemas import ContextBundle, TerminalError, PatchFile, TaskView
from perception.live_sandbox import validate_patch


@pytest.mark.parametrize('method,path,body', [
    ('GET', '/api/access', None), ('POST', '/api/access', {'capability':'modify_files','allowed':True}),
    ('POST', '/api/tasks', {'command':'synthetic'}), ('GET', '/api/tasks/synthetic', None),
    ('POST', '/api/tasks/synthetic/decision', {'proposal_id':'empty','decision':'approve'}),
    ('POST', '/api/tasks/synthetic/cancel', {}), ('GET', '/api/tasks/synthetic/screenshot', None),
    ('POST', '/api/tasks/synthetic/permissions/p', {'decision':'allow'}), ('GET','/openapi.json',None),
])
async def test_no_sensitive_route_accepts_an_unpaired_client(method, path, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8000') as client:
        response = await client.request(method, path, json=body)
        assert response.status_code == 401
        assert response.json()['error']['code'] == 'UNAUTHORIZED'


@pytest.mark.parametrize('host', ['attacker.example:8000','localhost.evil:8000','localhost:9999','127.0.0.1.evil:8000'])
async def test_foreign_host_rejected_even_with_valid_credentials(async_client, host):
    response = await async_client.get('/api/access', headers={'Host':host})
    assert response.status_code == 400


@pytest.mark.parametrize('origin', ['https://attacker.example','null','http://localhost:5173','http://127.0.0.1:8000'])
async def test_hostile_origin_rejected_even_with_credentials(async_client, origin):
    response = await async_client.post('/api/access', headers={'Origin':origin}, json={'capability':'modify_files','allowed':True})
    assert response.status_code == 403


async def test_browser_pairs_then_cookie_mutations_require_origin():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8000') as client:
        landing = await client.get('/')
        assert landing.status_code == 200 and settings.API_SESSION_TOKEN not in landing.text
        assert 'nonce-' in landing.headers['content-security-policy']
        assert (await client.post('/api/session', headers={'Authorization':'Bearer invalid'})).status_code == 401
        paired = await client.post('/api/session', headers={'Authorization':'Bearer '+settings.API_SESSION_TOKEN})
        assert paired.status_code == 204
        cookie = paired.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
        assert client.cookies[COOKIE] == settings.API_SESSION_TOKEN
        assert (await client.get('/api/access')).status_code == 200
        assert (await client.post('/api/access', json={'capability':'modify_files','allowed':True})).status_code == 403
        assert (await client.post('/api/access', headers={'Origin':'http://localhost:8000'}, json={'capability':'modify_files','allowed':True})).status_code == 200


async def test_pairing_cookie_expires_on_process_token_rotation(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8000', cookies={COOKIE:settings.API_SESSION_TOKEN}) as client:
        monkeypatch.setattr(settings, 'API_SESSION_TOKEN', 'rotated-session-token-that-is-at-least-32-characters')
        assert (await client.get('/api/access')).status_code == 401


async def test_dev_origin_is_explicit_and_same_host(async_client, monkeypatch):
    monkeypatch.setattr(settings, 'DEV_FRONTEND', True)
    assert (await async_client.get('/api/access', headers={'Origin':'http://localhost:5173'})).status_code == 200
    assert (await async_client.get('/api/access', headers={'Origin':'http://127.0.0.1:5173'})).status_code == 403


@pytest.mark.parametrize('path', ['.env','.env.production','.env.local','nested/.env.staging','.ssh/id_ed25519','.aws/credentials','service-account.json','private.pem'])
def test_secret_families_are_neither_context_nor_patch_targets(tmp_path, path):
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('CONNECTION_STRING=opaque-secret\n')
    bundle = ContextBundle(collected_at=datetime.now(timezone.utc), terminal_errors=[TerminalError(file=path,message='Synthetic',raw_excerpt='')])
    assert read_workspace_files(bundle,str(tmp_path)) == {}
    with pytest.raises(ValueError, match='Protected'):
        materialize_edit(FileEditFromModel(path=path,old_text='opaque-secret',new_text='changed'),str(tmp_path))
    patch = PatchFile(path=path,unified_diff='--- a/'+path+'\n+++ b/'+path+'\n@@ -1 +1 @@\n-CONNECTION_STRING=opaque-secret\n+changed\n')
    assert validate_patch(patch,tmp_path,tmp_path)[0] is False
    with pytest.raises(ValueError, match='CREDENTIAL'):
        safe_workspace(tmp_path,check_files=True)


def test_safe_example_is_available_but_application_root_is_never_mounted(tmp_path):
    (tmp_path/'.env.example').write_text('CONNECTION_STRING=\n')
    assert safe_workspace(tmp_path,check_files=True) == tmp_path
    with pytest.raises(ValueError, match='UNSAFE_WORKSPACE_ROOT'):
        safe_workspace(APP_ROOT)


def test_loopback_only_and_single_process_state_ownership(tmp_path):
    for host in ['127.0.0.1','localhost','::1']:
        require_loopback(host)
    for host in ['0.0.0.0','::','192.168.1.2','attacker.example']:
        with pytest.raises(ValueError):
            require_loopback(host)
    with instance_lock(tmp_path):
        with pytest.raises(RuntimeError):
            with instance_lock(tmp_path):
                pass
    with instance_lock(tmp_path):
        pass


def test_completed_history_is_bounded_and_active_tasks_survive(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(settings,'MAX_RETAINED_TASKS',1)
    for name, state, age in [('old','completed',4000),('recent','completed',20),('new','completed',10),('active','analyzing',5000)]:
        task_manager.tasks[name] = TaskView(task_id=name,state=state,command='Synthetic',created_at=now-timedelta(seconds=age),updated_at=now-timedelta(seconds=age),task_grants=['screen'])
        task_manager.cancel_events[name] = threading.Event()
    task_manager.prune_tasks(now)
    assert set(task_manager.tasks) == {'new','active'}
    assert task_manager.tasks['new'].task_grants == []
    assert set(task_manager.cancel_events) == {'active'}


async def test_production_assets_and_framework_errors_keep_contract(async_client):
    response = await async_client.get('/')
    assert response.status_code in {200,503}
    for path in ['/missing','/../.env','/%2e%2e/.env','/api/unknown']:
        response = await async_client.get(path)
        assert response.status_code == 404 and 'error' in response.json()
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-request-id']
        assert "img-src 'self' data: blob:" in response.headers['content-security-policy']
    response = await async_client.put('/api/access')
    assert response.status_code == 405 and response.json()['error']['code'] == 'METHOD_NOT_ALLOWED'
