"""Security-focused coverage for the central log redaction boundary."""

from __future__ import annotations

from io import StringIO
import logging

import pytest

import magi.utils.log_redaction as log_redaction
from magi.utils.log_redaction import (
    MASKED_LOG_VALUE,
    RedactingFormatter,
    RedactingTextStream,
    is_sensitive_log_field,
    redact_log_text,
    redact_log_value,
    redact_structlog_event,
    refresh_known_log_secrets,
)


def test_sensitive_fields_mask_credentials_without_hiding_token_metrics() -> None:
    payload = {
        "api-key": "secret-api-key",
        "X-QW-Api-Key": "secret-header-key",
        "accessToken": "secret-access-token",
        "nested": {"proxy_password": "secret-password"},
        "input_tokens": 123,
        "max_output_tokens": 456,
        "token_budget": 789,
        "private_network_allowlist": ["127.0.0.1"],
        "tokenizer": "cl100k_base",
    }

    redacted = redact_log_value(payload)

    assert redacted["api-key"] == MASKED_LOG_VALUE
    assert redacted["X-QW-Api-Key"] == MASKED_LOG_VALUE
    assert redacted["accessToken"] == MASKED_LOG_VALUE
    assert redacted["nested"]["proxy_password"] == MASKED_LOG_VALUE
    assert redacted["input_tokens"] == 123
    assert redacted["max_output_tokens"] == 456
    assert redacted["token_budget"] == 789
    assert redacted["private_network_allowlist"] == ["127.0.0.1"]
    assert redacted["tokenizer"] == "cl100k_base"


def test_sensitive_path_masks_sibling_value() -> None:
    redacted = redact_log_value(
        {
            "path": "llm.providers.primary.api_key",
            "value": "unlabeled-secret",
            "operation": "replace",
        }
    )

    assert redacted["value"] == MASKED_LOG_VALUE
    assert redacted["operation"] == "replace"


def test_text_redaction_covers_headers_urls_assignments_and_tokens() -> None:
    token = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    text = "\n".join(
        [
            "Authorization: Bearer header-secret",
            "Cookie: session=secret-cookie",
            "https://user:proxy-pass@example.test/path?api_key=query-secret&mode=debug",
            '{"client_secret": "json-secret", "input_tokens": 42}',
            "headers={'Cookie': 'session=dict-cookie-secret'}",
            '{"authorization": "Custom json-auth-secret"}',
            "cookie=assignment-cookie-secret",
            "authorization=assignment-auth-secret",
            "pwd=assignment-pwd-secret",
            "bearer=assignment-bearer-secret",
            "OPENAI_API_KEY=env-secret",
            f"provider key {token}",
            "token budget is useful diagnostics",
        ]
    )

    redacted = redact_log_text(text)

    for secret in (
        "header-secret",
        "secret-cookie",
        "proxy-pass",
        "query-secret",
        "json-secret",
        "dict-cookie-secret",
        "json-auth-secret",
        "assignment-cookie-secret",
        "assignment-auth-secret",
        "assignment-pwd-secret",
        "assignment-bearer-secret",
        "env-secret",
        token,
    ):
        assert secret not in redacted
    assert "mode=debug" in redacted
    assert '"input_tokens": 42' in redacted
    assert "token budget is useful diagnostics" in redacted


def test_configured_secret_exact_values_survive_rotation_and_url_encoding() -> None:
    old_secret = "old secret/+value"
    new_secret = "new-secret-value"
    refresh_known_log_secrets(
        {"llm": {"providers": {"main": {"api_key": old_secret}}}},
        environment={},
    )
    refresh_known_log_secrets(
        {"llm": {"providers": {"main": {"api_key": new_secret}}}},
        environment={},
    )

    redacted = redact_log_text(
        "plain="
        + old_secret
        + " encoded=old%20secret%2F%2Bvalue rotated="
        + new_secret
    )

    assert old_secret not in redacted
    assert "old%20secret%2F%2Bvalue" not in redacted
    assert new_secret not in redacted
    assert redacted.count(MASKED_LOG_VALUE) == 3


def test_short_configured_secret_is_redacted_inside_larger_text() -> None:
    refresh_known_log_secrets(
        {"proxy": {"password": "x7!"}},
        environment={},
    )

    redacted = redact_log_text("prefix-x7!-suffix")

    assert "x7!" not in redacted
    assert redacted == f"prefix-{MASKED_LOG_VALUE}-suffix"


def test_short_secret_does_not_destroy_normal_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(log_redaction, "_KNOWN_SECRET_VALUES", ())
    refresh_known_log_secrets(
        {"proxy": {"password": "a"}},
        environment={},
    )

    redacted = redact_log_text("a data remains readable")

    assert redacted == f"{MASKED_LOG_VALUE} data remains readable"


def test_mask_placeholder_is_not_registered_as_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(log_redaction, "_KNOWN_SECRET_VALUES", ())
    refresh_known_log_secrets({"llm": {"api_key": "***"}}, environment={})

    assert redact_log_text("separator *** remains visible") == (
        "separator *** remains visible"
    )


def test_environment_pwd_is_not_registered_as_a_secret() -> None:
    working_directory = "/tmp/log-redaction-working-directory-canary"
    environment_secret = "environment-secret-canary"
    refresh_known_log_secrets(
        {},
        environment={
            "PWD": working_directory,
            "OPENAI_API_KEY": environment_secret,
        },
    )

    redacted = redact_log_text(
        f"cwd={working_directory} key={environment_secret}"
    )

    assert working_directory in redacted
    assert environment_secret not in redacted


def test_binary_data_urls_and_private_keys_are_never_logged() -> None:
    image_data = "A" * 64
    private_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "sensitive-key-material\n"
        "-----END PRIVATE KEY-----"
    )

    redacted = redact_log_text(
        f"image=data:image/png;base64,{image_data}\nkey={private_key}"
    )

    assert image_data not in redacted
    assert "sensitive-key-material" not in redacted
    assert "[binary content omitted]" in redacted


def test_signed_url_credentials_are_masked() -> None:
    signature = "signed-url-value"
    credential = "temporary-access-key"

    redacted = redact_log_text(
        "https://example.test/object?"
        f"X-Amz-Credential={credential}&X-Amz-Signature={signature}&mode=download"
    )

    assert credential not in redacted
    assert signature not in redacted
    assert "mode=download" in redacted


def test_redacting_text_stream_buffers_split_secret_until_newline() -> None:
    secret = "split-stream-secret"
    refresh_known_log_secrets(
        {"llm": {"providers": {"main": {"api_key": secret}}}},
        environment={},
    )
    target = StringIO()
    stream = RedactingTextStream(target)

    stream.write("sidecar value=split-")
    stream.write("stream-secret")
    assert target.getvalue() == ""

    stream.write("\n")
    stream.flush()

    assert secret not in target.getvalue()
    assert MASKED_LOG_VALUE in target.getvalue()


def test_redacting_formatter_masks_message_arguments_and_exception_text() -> None:
    try:
        raise RuntimeError("request failed api_key=formatter-secret")
    except RuntimeError:
        exc_info = __import__("sys").exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer %s",
        args=("message-secret",),
        exc_info=exc_info,
    )
    rendered = RedactingFormatter("%(message)s").format(record)

    assert "message-secret" not in rendered
    assert "formatter-secret" not in rendered
    assert MASKED_LOG_VALUE in rendered


def test_structlog_processor_redacts_nested_events() -> None:
    event = redact_structlog_event(
        None,
        "info",
        {
            "event": "provider failed Authorization: Bearer event-secret",
            "headers": {"X-Api-Key": "nested-secret"},
            "input_tokens": 99,
        },
    )

    assert "event-secret" not in event["event"]
    assert event["headers"]["X-Api-Key"] == MASKED_LOG_VALUE
    assert event["input_tokens"] == 99


def test_field_classifier_avoids_common_false_positives() -> None:
    assert is_sensitive_log_field("refresh-token")
    assert is_sensitive_log_field("providerApiKey")
    assert not is_sensitive_log_field("max_tokens")
    assert not is_sensitive_log_field("private_network_allowlist")
    assert not is_sensitive_log_field("tokenizer")
