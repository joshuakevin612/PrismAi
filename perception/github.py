"""
perception/github.py
Fetches Pull Request metadata and unified diffs from GitHub API.
Handles rate limits, secret redaction, and diff truncation.
Never raises exceptions.
"""

import os
from typing import List, Optional, Tuple
import requests

from shared.schemas import DiffFile, GithubTarget, PullRequestContext
from perception.redactor import redact_secrets

MAX_PATCH_CHARS = 4000
GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_SEC = 5.0


def is_github_configured() -> bool:
    """Checks whether GITHUB_TOKEN is configured in the environment."""
    token = os.getenv("GITHUB_TOKEN")
    return bool(token and token.strip())


def fetch_pull_request(
    target: GithubTarget,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> Tuple[Optional[PullRequestContext], List[str]]:
    """
    Fetches PR details and file diffs from GitHub.
    Handles rate-limiting, network failures, and redaction gracefully.
    """
    warnings: List[str] = []
    token = os.getenv("GITHUB_TOKEN")

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Prism-AI-Perception/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"

    repo = target.repo.strip()
    pr_num = target.pr_number

    # 1. Fetch PR details
    pr_url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_num}"
    try:
        resp = requests.get(pr_url, headers=headers, timeout=timeout)
        if resp.status_code == 404:
            warnings.append(f"GITHUB_PR_NOT_FOUND: {repo}#{pr_num}")
            return None, warnings
        elif resp.status_code in (403, 429):
            # Check rate limit indicators
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining == "0" or "rate limit" in resp.text.lower():
                warnings.append("GITHUB_RATE_LIMITED")
            else:
                warnings.append(f"GITHUB_ACCESS_DENIED: HTTP {resp.status_code}")
            return None, warnings
        elif resp.status_code != 200:
            warnings.append(f"GITHUB_API_ERROR_{resp.status_code}")
            return None, warnings

        pr_data = resp.json()
    except requests.exceptions.Timeout:
        warnings.append("GITHUB_TIMEOUT")
        return None, warnings
    except requests.exceptions.RequestException as e:
        warnings.append(f"GITHUB_NETWORK_ERROR: {type(e).__name__}")
        return None, warnings

    title = redact_secrets(pr_data.get("title") or "")
    body = redact_secrets(pr_data.get("body") or "")
    base_ref = pr_data.get("base", {}).get("ref", "")
    head_ref = pr_data.get("head", {}).get("ref", "")

    # 2. Fetch PR files and diffs
    files_url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_num}/files"
    diff_files: List[DiffFile] = []
    try:
        f_resp = requests.get(files_url, headers=headers, timeout=timeout)
        if f_resp.status_code == 200:
            f_data = f_resp.json()
            for f in f_data:
                raw_patch = f.get("patch")
                is_truncated = False
                patch_str = None

                if raw_patch:
                    if len(raw_patch) > MAX_PATCH_CHARS:
                        raw_patch = raw_patch[:MAX_PATCH_CHARS] + "\n... [DIFF TRUNCATED]"
                        is_truncated = True
                    patch_str = redact_secrets(raw_patch)

                status_raw = f.get("status", "modified")
                status = status_raw if status_raw in ("added", "modified", "removed", "renamed") else "modified"

                diff_files.append(
                    DiffFile(
                        path=f.get("filename", ""),
                        status=status,
                        additions=int(f.get("additions", 0)),
                        deletions=int(f.get("deletions", 0)),
                        patch=patch_str,
                        truncated=is_truncated,
                    )
                )
        elif f_resp.status_code in (403, 429):
            warnings.append("GITHUB_RATE_LIMITED")
        else:
            warnings.append(f"GITHUB_FILES_FETCH_FAILED_{f_resp.status_code}")
    except requests.exceptions.RequestException as e:
        warnings.append(f"GITHUB_FILES_FETCH_ERROR: {type(e).__name__}")

    pr_context = PullRequestContext(
        repo=repo,
        number=pr_num,
        title=title,
        body=body,
        base=base_ref,
        head=head_ref,
        files=diff_files,
    )
    return pr_context, warnings
