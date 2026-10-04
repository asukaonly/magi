"""Host/plugin image contracts and capability boundary behavior."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, Mock



@pytest.mark.parametrize(
    "name",
    [
        "ImageArtifact",
        "ImageGenerationRequest",
        "ImageGenerationResponse",
        "ImageGenerationCapability",
        "ImageGenProviderError",
        "ImageGenAuthError",
        "ImageGenContentFilteredError",
        "ImageGenInvalidParameterError",
        "ImageGenRateLimitError",
        "ImageGenTimeoutError",
    ],
)
def test_image_contract_exports_share_types_across_host_and_plugin(name):
    import magi.llm.image_generation as host
    import magi_plugin_sdk.image_generation as sdk

    assert name in sdk.__all__
    assert getattr(host, name) is getattr(sdk, name)
    if name.startswith("ImageGen") and name.endswith("Error"):
        with pytest.raises(sdk.ImageGenProviderError, match="provider failed"):
            raise getattr(host, name)("provider failed")


@pytest.fixture
def capabilities():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    try:
        yield build_tool_capabilities()
    finally:
        reset_tool_capabilities()




def test_max_image_attachment_bytes_host_sdk_same_value():
    from magi.chat.attachment_ingestion import MAX_IMAGE_ATTACHMENT_BYTES as host_val
    from magi_plugin_sdk.image_generation import MAX_IMAGE_ATTACHMENT_BYTES as sdk_val
    assert host_val == sdk_val, (
        f"Host and SDK MAX_IMAGE_ATTACHMENT_BYTES must match: {host_val} != {sdk_val}"
    )



@pytest.mark.asyncio
async def test_chat_capability_forwards_reads_and_guards_attachment_mutations(
    capabilities, monkeypatch
):
    from magi.core.chat_assets.mutations import chat_asset_mutation_is_held

    read = Mock()
    read.get_attachment_payload.return_value = {"id": "attachment-1", "content": "stored"}
    monkeypatch.setattr("magi.chat.read_service.get_chat_read_service", lambda: read)
    attachment = {"id": "attachment-2", "mime": "image/png"}
    prepared, ingested = object(), object()

    def prepare(**kwargs):
        assert chat_asset_mutation_is_held()
        return prepared

    def ingest(**kwargs):
        assert chat_asset_mutation_is_held()
        return ingested

    service = Mock(
        prepare_runtime_attachment=Mock(side_effect=prepare),
        ingest_local_file=Mock(side_effect=ingest),
    )
    constructor = Mock(return_value=service)
    monkeypatch.setattr(
        "magi.chat.attachment_ingestion.LocalChatAttachmentIngestionService", constructor
    )
    assert capabilities.chat.get_attachment_payload("owner", "session-1", "attachment-1") == {
        "id": "attachment-1",
        "content": "stored",
    }
    read.get_attachment_payload.assert_called_once_with("owner", "session-1", "attachment-1")
    assert (
        await capabilities.chat.prepare_runtime_attachment(
            session_id="session-2", turn_id="turn-2", attachment=attachment
        )
        is prepared
    )
    service.prepare_runtime_attachment.assert_called_once_with(
        session_id="session-2", turn_id="turn-2", attachment=attachment
    )
    assert (
        await capabilities.chat.ingest_local_file(
            session_id="session-3",
            turn_id="turn-3",
            file_path="/test/picture.png",
            original_name="picture.png",
            mime_type="image/png",
        )
        is ingested
    )
    service.ingest_local_file.assert_called_once_with(
        session_id="session-3",
        turn_id="turn-3",
        file_path="/test/picture.png",
        original_name="picture.png",
        mime_type="image/png",
    )
    constructor.assert_called_once_with()
    assert not chat_asset_mutation_is_held()



@pytest.mark.asyncio
async def test_image_capability_forwards_adapter_selection_and_awaits_usage(
    capabilities, monkeypatch
):
    adapter = object()
    factory = Mock(return_value=adapter)
    publisher = AsyncMock()
    monkeypatch.setattr(
        "magi.llm.image_generation.factory.create_image_generation_adapter", factory
    )
    monkeypatch.setattr("magi.llm.usage_tracing.publish_llm_usage_span", publisher)
    selection = {
        "provider_id": "image-account",
        "provider_settings": object(),
        "model": "image-model",
        "registry": object(),
        "timeout": 43,
        "proxy_url": "http://proxy.test:8080",
    }
    assert capabilities.image_gen.create_adapter(**selection) is adapter
    factory.assert_called_once_with(**selection)
    usage = {
        "provider": "image-account",
        "model": "image-model",
        "request_kind": "image_generation",
        "success": False,
        "started_at": 100.0,
        "image_count": 0,
        "error": "provider failed",
        "event_context": {"turn_id": "turn-1", "session_id": "session-1"},
    }
    await capabilities.image_gen.publish_usage_span(**usage)
    publisher.assert_awaited_once_with(**usage)
