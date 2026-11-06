"""Compose shared speech synthesis for product APIs and output delivery."""
from __future__ import annotations
import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator
from ..core.container import require_binding
from ..identity import CANONICAL_LOCAL_USER
from ..speech.tts.contracts import MessageSource
from ..speech.tts.models import TTSModelStore
from ..speech.tts.service import SynthesisService
from ..speech.tts.engines import resolve_options
from ..config.loader import get_config
from magi_plugin_sdk.audio import AudioClip
from ..utils.runtime import get_runtime_paths

_service: SynthesisService | None = None


async def synthesize_delivery(text: str) -> AudioClip:
    """Resolve the selected speech engine at output time."""
    return await synthesis_service().synthesize_delivery(text, resolve_options(get_config()))


async def read_message(source: MessageSource) -> str:
    message = await require_binding("chat_read_service").aget_display_message(
        CANONICAL_LOCAL_USER, source.session_id, source.message_id, final_only=True)
    if (not message or message.role != "assistant" or message.kind != "assistant"
            or message.message_kind not in {"assistant_final", "assistant_rhythm_segment"}
            or hashlib.sha256(message.content.encode()).hexdigest() != source.revision):
        raise ValueError("stale_message")
    return message.content


def synthesis_service() -> SynthesisService:
    global _service
    if _service is None:
        paths = get_runtime_paths()
        _service = SynthesisService(paths.cache_dir / "tts", TTSModelStore(paths.models_cache_dir / "tts"), read_message,
                                   reference_root=paths.data_dir / "speech" / "voices")
    return _service


@asynccontextmanager
async def tts_clear_boundary() -> AsyncIterator[None]:
    # Initialize even after a restart so receipts and WAVs participate in full clear.
    async with synthesis_service().clear_boundary():
        yield
