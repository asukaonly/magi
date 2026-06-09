"""TDD tests for Phase 2 clusters F (ChatPort) and H (ImageGenPort + PROMOTE).

Asserts:
- build_tool_capabilities() wires .chat and .image_gen with correct method names.
- image-gen contract types are importable from magi_plugin_sdk.image_generation.
- Class identity is preserved (host re-export shims keep the same objects).
- MAX_IMAGE_ATTACHMENT_BYTES is importable from SDK and matches the host value.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Cluster H: image-gen PROMOTE — class identity
# ---------------------------------------------------------------------------

def test_image_artifact_importable_from_sdk():
    from magi_plugin_sdk.image_generation import ImageArtifact
    assert ImageArtifact is not None


def test_image_gen_provider_error_importable_from_sdk():
    from magi_plugin_sdk.image_generation import ImageGenProviderError
    assert ImageGenProviderError is not None


def test_image_generation_request_importable_from_sdk():
    from magi_plugin_sdk.image_generation import ImageGenerationRequest
    assert ImageGenerationRequest is not None


def test_image_gen_sdk_exports_all_error_types():
    from magi_plugin_sdk.image_generation import (
        ImageGenAuthError,
        ImageGenContentFilteredError,
        ImageGenInvalidParameterError,
        ImageGenRateLimitError,
        ImageGenTimeoutError,
    )
    assert issubclass(ImageGenAuthError, Exception)
    assert issubclass(ImageGenRateLimitError, Exception)
    assert issubclass(ImageGenContentFilteredError, Exception)
    assert issubclass(ImageGenInvalidParameterError, Exception)
    assert issubclass(ImageGenTimeoutError, Exception)


def test_image_artifact_host_sdk_class_identity():
    """Host re-export shim must point to the same class object as the SDK."""
    from magi.llm.image_generation import ImageArtifact as HostArtifact
    from magi_plugin_sdk.image_generation import ImageArtifact as SdkArtifact
    assert HostArtifact is SdkArtifact, (
        "magi.llm.image_generation.ImageArtifact must be the same object as "
        "magi_plugin_sdk.image_generation.ImageArtifact"
    )


def test_image_gen_errors_host_sdk_class_identity():
    from magi.llm.image_generation import ImageGenProviderError as H
    from magi_plugin_sdk.image_generation import ImageGenProviderError as S
    assert H is S

    from magi.llm.image_generation import ImageGenAuthError as H2
    from magi_plugin_sdk.image_generation import ImageGenAuthError as S2
    assert H2 is S2


def test_image_generation_request_host_sdk_class_identity():
    from magi.llm.image_generation import ImageGenerationRequest as H
    from magi_plugin_sdk.image_generation import ImageGenerationRequest as S
    assert H is S


# ---------------------------------------------------------------------------
# Cluster F: MAX_IMAGE_ATTACHMENT_BYTES promoted to SDK
# ---------------------------------------------------------------------------

def test_max_image_attachment_bytes_importable_from_sdk():
    from magi_plugin_sdk.image_generation import MAX_IMAGE_ATTACHMENT_BYTES
    assert isinstance(MAX_IMAGE_ATTACHMENT_BYTES, int)
    assert MAX_IMAGE_ATTACHMENT_BYTES > 0


def test_max_image_attachment_bytes_host_sdk_same_value():
    from magi.chat.attachment_ingestion import MAX_IMAGE_ATTACHMENT_BYTES as host_val
    from magi_plugin_sdk.image_generation import MAX_IMAGE_ATTACHMENT_BYTES as sdk_val
    assert host_val == sdk_val, (
        f"Host and SDK MAX_IMAGE_ATTACHMENT_BYTES must match: {host_val} != {sdk_val}"
    )


# ---------------------------------------------------------------------------
# Cluster F: ChatPort wired in build_tool_capabilities
# ---------------------------------------------------------------------------

def test_chat_port_wired():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    assert caps.chat is not None, "chat port must be wired"
    assert hasattr(caps.chat, "get_attachment_payload"), (
        "chat must expose get_attachment_payload"
    )
    assert hasattr(caps.chat, "prepare_runtime_attachment"), (
        "chat must expose prepare_runtime_attachment"
    )
    assert hasattr(caps.chat, "ingest_local_file"), (
        "chat must expose ingest_local_file"
    )
    reset_tool_capabilities()


def test_chat_port_protocol_in_sdk():
    from magi_plugin_sdk.capabilities import ChatPort
    assert ChatPort is not None


# ---------------------------------------------------------------------------
# Cluster H: ImageGenPort wired in build_tool_capabilities
# ---------------------------------------------------------------------------

def test_image_gen_port_wired():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    assert caps.image_gen is not None, "image_gen port must be wired"
    assert hasattr(caps.image_gen, "create_adapter"), (
        "image_gen must expose create_adapter"
    )
    assert hasattr(caps.image_gen, "publish_usage_span"), (
        "image_gen must expose publish_usage_span"
    )
    reset_tool_capabilities()


def test_image_gen_port_protocol_in_sdk():
    from magi_plugin_sdk.capabilities import ImageGenPort
    assert ImageGenPort is not None
