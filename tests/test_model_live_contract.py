"""Exercise the NVIDIA HTTP boundary without spending real API quota."""
import asyncio
import json
import httpx
import pytest
from backend.config import settings
from backend.model_client import ModelClient, ModelClientException

PLAN = {'summary': 'Diagnosis', 'root_cause': 'Missing field', 'explanation': 'Use a default',
        'confidence': 0.9, 'proposals': []}


@pytest.fixture
def nvidia(monkeypatch):
    return ModelClient(api_key='nvapi-local-test', model='nvidia/nemotron-3-super-120b-a12b')


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))


async def test_nvidia_request_and_success(nvidia, monkeypatch):
    def handler(request):
        assert str(request.url) == 'https://integrate.api.nvidia.com/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer nvapi-local-test'
        body = json.loads(request.content)
        assert body['stream'] is False and body['reasoning_effort'] == 'none'
        assert 'response_format' not in body
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(PLAN)}}]})
    transport(monkeypatch, handler)
    assert (await nvidia.analyze('diagnose', {})).summary == 'Diagnosis'


async def test_lightning_uses_its_supported_thinking_control(nvidia, monkeypatch):
    nvidia.model = 'nvidia/nemotron-3.5-lightning-30b-a3b'
    def handler(request):
        body = json.loads(request.content)
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        assert 'reasoning_effort' not in body
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(PLAN)}}]})
    transport(monkeypatch, handler)
    assert (await nvidia.analyze('diagnose', {})).summary == 'Diagnosis'


@pytest.mark.parametrize('status,retryable', [(401, False), (403, False), (404, False), (422, False), (429, True), (503, True)])
async def test_provider_errors_are_safe_and_have_correct_retryability(nvidia, monkeypatch, status, retryable):
    transport(monkeypatch, lambda request: httpx.Response(status, text='private-provider-details'))
    with pytest.raises(ModelClientException) as caught:
        await nvidia.analyze('diagnose', {})
    assert caught.value.retryable is retryable
    assert 'private-provider-details' not in caught.value.message


async def test_malformed_envelope_retries_then_reports_invalid(nvidia, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': []})
    transport(monkeypatch, handler)
    with pytest.raises(ModelClientException) as caught:
        await nvidia.analyze('diagnose', {})
    assert caught.value.code == 'MODEL_INVALID_RESPONSE' and len(calls) == 3


async def test_invalid_json_can_be_corrected(nvidia, monkeypatch):
    replies = iter(['bad json', '```json\n' + json.dumps(PLAN) + '\n```'])
    transport(monkeypatch, lambda request: httpx.Response(200, json={'choices': [{'message': {'content': next(replies)}}]}))
    assert (await nvidia.analyze('diagnose', {})).confidence == 0.9


async def test_incomplete_patch_is_repaired_before_review(nvidia, monkeypatch, tmp_path):
    (tmp_path / 'app.py').write_text('before\n')
    def response(diff):
        plan = dict(PLAN, proposals=[{'id':'fix','title':'Fix','rationale':'Fix','risk':'low',
            'files':[{'path':'app.py','unified_diff':diff}], 'commands':[]}])
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan)}}]})
    replies = iter(['-before\n+after\n','--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-before\n+after\n'])
    transport(monkeypatch, lambda request: response(next(replies)))
    analysis = await nvidia.analyze('fix', {}, allowed_root=str(tmp_path))
    assert analysis.proposals[0].policy_ok
    assert analysis.proposals[0].files[0].unified_diff.startswith('--- a/app.py')
    assert (tmp_path / 'app.py').read_text() == 'before\n'


async def test_model_timeout_is_bounded(nvidia, monkeypatch):
    monkeypatch.setattr(settings, 'MODEL_TIMEOUT_SECONDS', 0.05)
    async def handler(request):
        await asyncio.sleep(10)
    transport(monkeypatch, handler)
    with pytest.raises(ModelClientException) as caught:
        await nvidia.analyze('diagnose', {})
    assert caught.value.code == 'MODEL_UNAVAILABLE' and caught.value.retryable


async def test_model_cancellation_propagates(nvidia, monkeypatch):
    entered = asyncio.Event()
    async def handler(request):
        entered.set()
        await asyncio.sleep(10)
    transport(monkeypatch, handler)
    job = asyncio.create_task(nvidia.analyze('diagnose', {}))
    await asyncio.wait_for(entered.wait(), 1)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job


async def test_missing_key_does_not_call_provider(nvidia):
    nvidia.api_key = ''
    with pytest.raises(ModelClientException) as caught:
        await nvidia.analyze('diagnose', {})
    assert caught.value.code == 'MODEL_CONFIGURATION_ERROR'

async def test_context_planner_uses_no_collected_data(nvidia, monkeypatch):
    def handler(request):
        body=json.loads(request.content)
        assert body['messages'][1]['content']=='Why did my terminal error?'
        assert 'budgeted_context' not in body['messages'][1]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'sources':[{'source':'terminal','reason':'Read the error'}]})}}]})
    transport(monkeypatch, handler)
    plan=await nvidia.plan_context('Why did my terminal error?')
    assert [s.source for s in plan.sources]==['terminal']

async def test_context_planner_rejects_unknown_sources(nvidia, monkeypatch):
    transport(monkeypatch,lambda request:httpx.Response(200,json={'choices':[{'message':{'content':'{"sources":[{"source":"all_files","reason":"no"}]}'}}]}))
    with pytest.raises(ModelClientException) as caught:
        await nvidia.plan_context('Inspect')
    assert caught.value.code=='MODEL_INVALID_RESPONSE'
