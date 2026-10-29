"""
perception/processes.py
Collects running processes using psutil, with command-line secret redaction.
Limits output to dev-relevant or top resource consumers.
"""

from typing import List, Tuple
import psutil

from shared.schemas import ProcessInfo
from perception.redactor import redact_secrets

# Developer process keywords to prioritize
DEV_PROCESS_KEYWORDS = {
    "python", "node", "npm", "git", "docker", "uvicorn", "fastapi",
    "pytest", "cargo", "go", "code", "bash", "zsh", "powershell",
    "cmd", "java", "ruby", "rustc", "webpack", "vite", "deno",
}


def collect_processes(
    limit: int = 25,
) -> Tuple[List[ProcessInfo], List[str]]:
    """
    Collects active processes with redacted command lines.
    Prioritizes developer tooling and top CPU/Memory consumers.
    Never raises exceptions.
    """
    warnings: List[str] = []
    collected: List[ProcessInfo] = []

    try:
        raw_list = []
        for proc in psutil.process_iter(
            attrs=["pid", "name", "cmdline", "cpu_percent", "memory_info"]
        ):
            try:
                info = proc.info
                pid = info.get("pid")
                name = info.get("name") or "unknown"
                cmdline_list = info.get("cmdline") or []
                cmdline_str = " ".join(cmdline_list) if cmdline_list else name

                # Secret redact command line
                cmdline_redacted = redact_secrets(cmdline_str)

                mem_bytes = (
                    info["memory_info"].rss if info.get("memory_info") else 0
                )
                mem_mb = round(mem_bytes / (1024 * 1024), 2)
                cpu_pct = float(info.get("cpu_percent") or 0.0)

                is_dev = any(k in name.lower() for k in DEV_PROCESS_KEYWORDS)

                raw_list.append(
                    (
                        is_dev,
                        mem_mb + (cpu_pct * 10),  # sort weight
                        ProcessInfo(
                            pid=pid,
                            name=name,
                            cmdline=cmdline_redacted,
                            cpu_percent=cpu_pct,
                            mem_mb=mem_mb,
                        ),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # Sort: developer processes first, then highest resource usage
        raw_list.sort(key=lambda item: (item[0], item[1]), reverse=True)
        collected = [item[2] for item in raw_list[:limit]]

    except Exception as e:
        warnings.append(f"PROCESS_COLLECT_FAILED: {type(e).__name__}")

    return collected, warnings
