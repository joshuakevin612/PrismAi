"""
perception/redactor.py
High-performance secret redactor for OCR, terminal excerpts, process cmdlines, and diffs.
Ensures no credentials, private keys, tokens, or .env values escape to external models.
"""

import os
import re
from typing import Optional, Set

# Named regex replacement rules (pattern, replacement)
SECRET_RULES = [
    # 1. Private Keys (PEM blocks)
    (
        re.compile(
            r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # 2. GitHub Tokens (classic, fine-grained, oauth)
    (re.compile(r"\b(ghp_[a-zA-Z0-9]{36,40})\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(gho_[a-zA-Z0-9]{36,40})\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(github_pat_[a-zA-Z0-9_]{22,82})\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(ghs_[a-zA-Z0-9]{36,40})\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(ghu_[a-zA-Z0-9]{36,40})\b"), "[REDACTED_SECRET]"),
    # 3. OpenAI / Nebius / Anthropic / Generic API keys starting with sk-
    (re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,80})\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(sk-ant-[a-zA-Z0-9_\-]{20,80})\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(sk-proj-[a-zA-Z0-9_\-]{20,80})\b"), "[REDACTED_SECRET]"),
    # 4. AWS Access Key ID
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "[REDACTED_SECRET]"),
    # 5. AWS Secret Access Key
    (
        re.compile(r"(?i)\b(aws_secret_access_key\s*[:=]\s*['\"]?)([A-Za-z0-9/+=]{40})(['\"]?)"),
        r"\1[REDACTED_SECRET]\3",
    ),
    # 6. Slack Tokens
    (re.compile(r"\b(xox[baprs]-[0-9]{10,13}-[a-zA-Z0-9_-]{10,40})\b"), "[REDACTED_SECRET]"),
    # 7. Google API Key / AI Studio
    (re.compile(r"\b(AIza[0-9A-Za-z\\-_]{35})\b"), "[REDACTED_SECRET]"),
    # 8. JWT Tokens (3 base64url sections separated by dot)
    (re.compile(r"\b(eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})\b"), "[REDACTED_SECRET]"),
    # 9. Bearer tokens in headers or logs
    (re.compile(r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{16,})\b"), r"\1[REDACTED_SECRET]"),
    # 10. URI with embedded credentials (e.g. postgres://user:password@host)
    (re.compile(r"(?i)\b([a-z]+://[^:\s]+:)([^@\s/]+)(@)"), r"\1[REDACTED_PASSWORD]\3"),
    # 11. Key-value secret assignments in config, logs, or cmdline
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api_key|apikey|access_token|auth_token|secret_key|private_key)"
            r"(\s*[:=]\s*['\"]?)([^\s'\"&;<>]{6,})(['\"]?)",
        ),
        r"\1\2[REDACTED_SECRET]\4",
    ),
]


class SecretRedactor:
    """Scans and replaces sensitive secrets with [REDACTED_SECRET]."""

    def __init__(self, additional_secrets: Optional[Set[str]] = None):
        self._exact_secrets: Set[str] = set()
        if additional_secrets:
            for s in additional_secrets:
                if s and len(s.strip()) >= 4:
                    self._exact_secrets.add(s.strip())

        # Also pull sensitive variables from environment
        self._harvest_env_secrets()

    def _harvest_env_secrets(self) -> None:
        """Harvest values from environment variables that likely contain credentials."""
        sensitive_keywords = (
            "SECRET",
            "KEY",
            "TOKEN",
            "PASSWORD",
            "PASSWD",
            "CREDENTIAL",
            "AUTH",
            "PRIVATE",
        )
        for k, v in os.environ.items():
            k_upper = k.upper()
            if any(keyword in k_upper for keyword in sensitive_keywords):
                v_clean = v.strip()
                # Ignore very short or trivial dummy values
                if len(v_clean) >= 6 and not v_clean.startswith("http"):
                    self._exact_secrets.add(v_clean)

    def add_secret(self, secret: str) -> None:
        """Register an additional specific secret string to redact."""
        if secret and len(secret.strip()) >= 4:
            self._exact_secrets.add(secret.strip())

    def redact(self, text: Optional[str]) -> str:
        """Redacts all discovered secrets from input text."""
        if not text:
            return ""

        redacted = text

        # 1. Exact match replacements for harvested environment secrets
        for secret in sorted(self._exact_secrets, key=len, reverse=True):
            if secret in redacted:
                redacted = redacted.replace(secret, "[REDACTED_SECRET]")

        # 2. Pattern replacements
        for pattern, replacement in SECRET_RULES:
            redacted = pattern.sub(replacement, redacted)

        return redacted


# Global default instance
_DEFAULT_REDACTOR = SecretRedactor()


def redact_secrets(text: Optional[str]) -> str:
    """Convenience functional interface for redacting secrets."""
    return _DEFAULT_REDACTOR.redact(text)


def register_secret(secret: str) -> None:
    """Register a known secret to redact globally."""
    _DEFAULT_REDACTOR.add_secret(secret)
