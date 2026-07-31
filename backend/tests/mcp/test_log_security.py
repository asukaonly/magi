"""MCP-specific credential registration and redaction coverage."""

from __future__ import annotations

from magi.mcp.log_security import (
    redact_mcp_log_text,
    register_mcp_runtime_secrets,
    register_mcp_transport_secrets,
)
from magi.utils.log_redaction import redact_log_text


def test_transport_registration_handles_custom_values_and_credential_forms() -> None:
    env_secret = "unusual-mcp-environment-secret"
    bearer_secret = "bearer-token-body-secret"
    url_password = "mcp-url-password-secret"
    query_signature = "mcp-query-signature-secret"
    arg_secret = "mcp-header-argument-secret"
    register_mcp_transport_secrets(
        {
            "transport": {
                "kind": "stdio",
                "url": (
                    f"https://user:{url_password}@example.test/mcp"
                    f"?X-Amz-Signature={query_signature}"
                ),
                "env": {"UNUSUAL_SETTING": env_secret},
                "headers": {"Authorization": f"Bearer {bearer_secret}"},
                "args": ["--header", f"X-Custom: {arg_secret}"],
            }
        }
    )

    rendered = redact_mcp_log_text(
        " ".join(
            [
                env_secret,
                bearer_secret,
                url_password,
                query_signature,
                arg_secret,
            ]
        )
    )

    for secret in (
        env_secret,
        bearer_secret,
        url_password,
        query_signature,
        arg_secret,
    ):
        assert secret not in rendered


def test_runtime_session_secret_is_masked_globally() -> None:
    session_secret = "mcp-session-runtime-secret"
    register_mcp_runtime_secrets([session_secret])

    assert session_secret not in redact_mcp_log_text(session_secret)
    assert session_secret not in redact_log_text(session_secret)


def test_short_custom_transport_value_is_masked_in_general_llm_logs() -> None:
    secret = "abc7890"
    register_mcp_transport_secrets(
        {"transport": {"kind": "stdio", "env": {"UNUSUAL_SETTING": secret}}}
    )

    assert secret not in redact_log_text(f"tool result={secret}")
