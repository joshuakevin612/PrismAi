"""
tests/test_redactor.py
Tests secret redaction across various credential types.
"""

import os


def test_unregistered_nvidia_credential_is_redacted():
    from perception.redactor import SecretRedactor
    key = 'nvapi-' + 'UnregisteredSyntheticValue' * 3
    assert key not in SecretRedactor().redact('NVIDIA_API_KEY=' + key)
from perception.redactor import SecretRedactor, redact_secrets, register_secret


def test_redact_github_token():
    text = "Clone repo using token: ghp_123456789012345678901234567890123456 and push."
    redacted = redact_secrets(text)
    assert "ghp_123456789012345678901234567890123456" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_redact_openai_nebius_key():
    text = "Authorization: Bearer sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    redacted = redact_secrets(text)
    assert "sk-ant-" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_redact_aws_keys():
    text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\naws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    redacted = redact_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in redacted


def test_redact_private_key():
    pem = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y1+abcdefghijklmnopqrstuvwxyz
-----END RSA PRIVATE KEY-----"""
    text = f"Key dump:\n{pem}\nEnd of log."
    redacted = redact_secrets(text)
    assert "MIIEowIBAAKCAQEA0Y1+" not in redacted
    assert "[REDACTED_PRIVATE_KEY]" in redacted


def test_redact_uri_passwords():
    uri = "postgres://postgres:super_secret_pw123@localhost:5432/mydb"
    redacted = redact_secrets(uri)
    assert "super_secret_pw123" not in redacted
    assert "[REDACTED_PASSWORD]" in redacted


def test_redact_env_secrets():
    os.environ["SECRET_PRISM_KEY"] = "super-confidential-token-999"
    redactor = SecretRedactor()
    res = redactor.redact("Failed sending token super-confidential-token-999 to service")
    assert "super-confidential-token-999" not in res
    assert "[REDACTED_SECRET]" in res
