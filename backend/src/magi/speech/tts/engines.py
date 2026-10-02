"""Inference adapters return complete validated audio and never play it."""

import asyncio
import io
import threading
import wave
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from magi_plugin_sdk.audio import AudioClip

from magi.config.models import AppConfig
from .models import LOCAL_VOICES, MODEL_ID, REMOTE_VOICES, VOICE_NAMES, ModelManager


@dataclass(frozen=True)
class EngineOptions:
    engine: str
    model: str
    voice: str
    speed: float
    base_url: str = ""
    api_key: str = ""
    timeout: int = 90


def resolve_options(config: AppConfig) -> EngineOptions:
    selection = config.speech.tts
    if selection.engine == "local":
        if selection.local_voice not in {voice.id for voice in LOCAL_VOICES}:
            raise ValueError("invalid_voice")
        return EngineOptions("local", MODEL_ID, selection.local_voice, selection.local_speed)
    provider = config.llm.providers.get(selection.provider_id or "")
    if not provider or not provider.enabled or not provider.services.tts.enabled:
        raise ValueError("provider_not_configured")
    service = provider.services.tts
    base_url = service.base_url or provider.base_url or ("https://api.openai.com/v1" if provider.provider_type == "openai" else "")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid_endpoint")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("invalid_endpoint")
    if not service.model or not service.voice or service.response_format != "wav":
        raise ValueError("provider_not_configured")
    if parsed.hostname == "api.openai.com":
        voices = REMOTE_VOICES if service.model == "gpt-4o-mini-tts" else [v for v in REMOTE_VOICES if v not in {"ballad", "verse", "marin", "cedar"}]
        if service.model not in {"gpt-4o-mini-tts", "tts-1", "tts-1-hd"} or service.voice not in voices:
            raise ValueError("invalid_voice")
    return EngineOptions("remote", service.model, service.voice, service.speed, base_url,
                         service.api_key or provider.api_key or "", service.timeout)


def pcm_wav(samples: bytes, sample_rate: int) -> AudioClip:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples)
    return AudioClip(data=output.getvalue())


class TTSEngine:
    def __init__(self, models: ModelManager) -> None:
        self.models = models
        self._local = None
        self._lock = asyncio.Lock()

    def unload(self) -> None:
        self._local = None

    async def synthesize(self, text: str, options: EngineOptions, cancellation: threading.Event) -> AudioClip:
        async with self._lock:
            if cancellation.is_set():
                raise ValueError("cancelled")
            if options.engine == "remote":
                return await self._remote(text, options, cancellation)
            self.models.in_use = True
            try:
                # Do not cancel this thread: ownership stays held until inference returns.
                return await asyncio.to_thread(self._local_synthesize, text, options, cancellation)
            finally:
                self.models.in_use = False

    def _local_synthesize(self, text: str, options: EngineOptions, cancellation: threading.Event) -> AudioClip:
        import numpy as np
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise ValueError("runtime_missing") from exc
        if self._local is None:
            self.models.verify()
            root = self.models.directory
            kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(root / "model.onnx"), voices=str(root / "voices.bin"),
                tokens=str(root / "tokens.txt"), data_dir=str(root / "espeak-ng-data"),
                lexicon=",".join(str(root / name) for name in ("lexicon-us-en.txt", "lexicon-zh.txt")),
            )
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(kokoro=kokoro, num_threads=2, provider="cpu"),
                rule_fsts=",".join(str(root / name) for name in ("date-zh.fst", "phone-zh.fst", "number-zh.fst")),
                max_num_sentences=1,
            )
            if not config.validate():
                raise ValueError("model_invalid")
            self._local = sherpa_onnx.OfflineTts(config)
        if cancellation.is_set():
            raise ValueError("cancelled")
        audio = self._local.generate(text, sid=VOICE_NAMES.index(options.voice), speed=options.speed,
                                     callback=lambda *_: 0 if cancellation.is_set() else 1)
        if cancellation.is_set():
            raise ValueError("cancelled")
        samples = (np.clip(audio.samples, -1, 1) * 32767).astype("<i2").tobytes()
        return pcm_wav(samples, audio.sample_rate)

    async def _remote(self, text: str, options: EngineOptions, cancellation: threading.Event) -> AudioClip:
        headers = {"Authorization": f"Bearer {options.api_key}"} if options.api_key else {}
        async with httpx.AsyncClient(timeout=options.timeout, follow_redirects=False) as client:
            async with client.stream("POST", options.base_url.rstrip("/") + "/audio/speech", headers=headers,
                                     json={"model": options.model, "voice": options.voice, "input": text,
                                           "speed": options.speed, "response_format": "wav"}) as response:
                if response.status_code != 200:
                    raise ValueError("provider_rejected")
                data = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    if cancellation.is_set():
                        raise ValueError("cancelled")
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024:
                        raise ValueError("audio_too_large")
        return AudioClip(data=bytes(data))
