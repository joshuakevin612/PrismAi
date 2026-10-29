"""M1 collectors with a shared deadline and partial-result handling."""
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from shared.schemas import ContextBundle, ContextRequest
from perception.screen import capture_screen
from perception.terminal import collect_terminal_errors
from perception.processes import collect_processes
from perception.github import fetch_pull_request

TOTAL_TIMEOUT_SECONDS = 7.5


def collect_context(req: ContextRequest) -> ContextBundle:
    bundle = ContextBundle(collected_at=datetime.now(timezone.utc))
    executor = ThreadPoolExecutor(max_workers=4)
    futures = {}
    try:
        if req.include_screen:
            futures[executor.submit(capture_screen)] = ('screen', 'screen')
        if req.include_terminal:
            futures[executor.submit(collect_terminal_errors)] = ('terminal', 'terminal_errors')
        if req.include_processes:
            futures[executor.submit(collect_processes)] = ('processes', 'processes')
        if req.github:
            futures[executor.submit(fetch_pull_request, req.github)] = ('github', 'pull_request')
        done, pending = wait(futures, timeout=TOTAL_TIMEOUT_SECONDS)
        for future in futures:
            name, field = futures[future]
            if future in pending:
                future.cancel()
                bundle.warnings.append(f'TIMEOUT_{name.upper()}')
                continue
            try:
                value, warnings = future.result()
                setattr(bundle, field, value)
                bundle.warnings.extend(warnings)
            except Exception as exc:
                bundle.warnings.append(f'ERROR_{name.upper()}: {type(exc).__name__}')
    except Exception as exc:
        bundle.warnings.append(f'CONTEXT_COLLECTION_FAILED: {type(exc).__name__}')
    finally:
        # A context manager would wait for timed-out workers here.
        # Workers can finish their bounded I/O but never mutate this bundle.
        executor.shutdown(wait=False, cancel_futures=True)
    return bundle
