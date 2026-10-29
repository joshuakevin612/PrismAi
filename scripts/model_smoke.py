"""Optional provider check: synthetic instructions, no screen/files/logs/processes."""
import asyncio
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))


async def main():
    from backend.model_client import ModelClient, ModelClientException
    client = ModelClient()
    try:
        plan = await client.plan_context('Release connectivity check only. No workstation context is needed; select no sources.')
        if plan.sources:
            raise RuntimeError('Provider requested context during a no-context check; none was collected.')
        with tempfile.TemporaryDirectory(prefix='prism-model-smoke-') as folder:
            result = await client.analyze('Release connectivity check. No evidence was supplied. Explain this limitation and return no proposals.',
                {'ocr_text':'','terminal_errors':[],'processes':[],'pull_request':None,'workspace_files':{},
                 'unavailable_sources':['screen','terminal','processes'],
                 'execution':{'commands_isolated':False,'access':{},'task_grants':[]}},folder)
        if result.proposals:
            raise RuntimeError('Provider proposed actions during a no-evidence check; no actions were executed.')
        print('PASS: real context planning and structured analysis; no workstation context or actions.')
        return 0
    except ModelClientException as exc:
        print(f'Provider check failed: {exc.code}; retryable={exc.retryable}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
