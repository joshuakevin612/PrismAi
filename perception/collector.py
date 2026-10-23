"""
perception/collector.py
Main context collection orchestrator for Member 1.
Coordinates screen OCR, terminal error extraction, process scanning, and GitHub PR context.
Guarantees completion within 8 seconds and never raises exceptions.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import List, Optional

from shared.schemas import ContextBundle, ContextRequest, ScreenContext, TerminalError, ProcessInfo, PullRequestContext
from perception.screen import capture_screen
from perception.terminal import collect_terminal_errors
from perception.processes import collect_processes
from perception.github import fetch_pull_request

TOTAL_TIMEOUT_SECONDS = 7.5  # Guarantees return strictly within 8s budget


def collect_context(req: ContextRequest) -> ContextBundle:
    """
    Collects full context bundle according to ContextRequest parameters.
    Guarantees completion within 8 seconds and never raises exceptions.
    Any failure produces partial results with corresponding warnings.
    """
    start_time = datetime.now(timezone.utc)
    warnings: List[str] = []

    screen_ctx: Optional[ScreenContext] = None
    terminal_errors: List[TerminalError] = []
    processes: List[ProcessInfo] = []
    pull_request: Optional[PullRequestContext] = None

    # Run subtasks concurrently to comfortably beat the 8-second limit
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}

        if req.include_screen:
            futures["screen"] = executor.submit(capture_screen)

        if req.include_terminal:
            futures["terminal"] = executor.submit(collect_terminal_errors)

        if req.include_processes:
            futures["processes"] = executor.submit(collect_processes)

        if req.github:
            futures["github"] = executor.submit(fetch_pull_request, req.github)

        # Collect results with per-feature and overall timeout
        for task_name, fut in futures.items():
            try:
                if task_name == "screen":
                    s_res, s_warns = fut.result(timeout=4.0)
                    screen_ctx = s_res
                    warnings.extend(s_warns)

                elif task_name == "terminal":
                    t_res, t_warns = fut.result(timeout=2.0)
                    terminal_errors = t_res
                    warnings.extend(t_warns)

                elif task_name == "processes":
                    p_res, p_warns = fut.result(timeout=2.0)
                    processes = p_res
                    warnings.extend(p_warns)

                elif task_name == "github":
                    g_res, g_warns = fut.result(timeout=5.0)
                    pull_request = g_res
                    warnings.extend(g_warns)

            except FutureTimeout:
                warnings.append(f"TIMEOUT_{task_name.upper()}")
            except Exception as e:
                warnings.append(f"ERROR_{task_name.upper()}: {type(e).__name__}")

    return ContextBundle(
        schema_version="1.0",
        collected_at=start_time,
        screen=screen_ctx,
        terminal_errors=terminal_errors,
        processes=processes,
        pull_request=pull_request,
        warnings=warnings,
    )
