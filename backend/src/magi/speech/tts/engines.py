"""Inference adapters return complete validated audio and never play it."""

import asyncio
import json
import io
import threading
import wave
from dataclasses import dataclass
from typing import Sequence
from urllib.parse import urlsplit

import httpx
from magi_plugin_sdk.audio import AudioClip

from magi.config.models import AppConfig
from .catalog import endpoint, provider_models
from .models import MELO_ID, VOICE_NAMES, TTSModelStore, local_voices


@dataclass(frozen=True)
class EngineOptions:
    engine: str
    model: str
    voice: str
    speed: float
    base_url: str = ""
    api_key: str = ""
    timeout: int = 90
    proxy_url: str | None = None
    protocol: str = "openai"
    instructions: str = ""
    emotion: str = ""


def resolve_options(config: AppConfig) -> EngineOptions:
    selection = config.speech.tts
    if selection.engine == "local":
        if selection.local_voice not in {voice.id for voice in local_voices(selection.local_model)}:
            raise ValueError("invalid_voice")
        return EngineOptions("local", selection.local_model, selection.local_voice, selection.local_speed)
    provider = config.llm.providers.get(selection.provider_id or "")
    if not provider or not provider.enabled or not provider.services.tts.enabled:
        raise ValueError("provider_not_configured")
    service = provider.services.tts
    base_url = endpoint(provider)
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid_endpoint")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("invalid_endpoint")
    if not selection.remote_model.strip() or not selection.remote_voice.strip():
        raise ValueError("provider_not_configured")
    capability = next((model for model in provider_models(selection.provider_id, provider)
                       if model.model_id == selection.remote_model or model.custom_model), None)
    if capability is None:
        raise ValueError("invalid_model")
    if not capability.custom_voice and selection.remote_voice not in {v.id for v in capability.voices}:
        raise ValueError("invalid_voice")
    if capability.speed_min is None:
        if selection.remote_speed != 1:
            raise ValueError("unsupported_parameter")
    elif not capability.speed_min <= selection.remote_speed <= capability.speed_max:
        raise ValueError("unsupported_parameter")
    if (selection.instructions and not capability.instructions) or (
            selection.emotion and selection.emotion not in capability.emotions):
        raise ValueError("unsupported_parameter")
    key = service.api_key or provider.api_key or ""
    if service.protocol in {"minimax", "dashscope"} and not key:
        raise ValueError("provider_not_configured")
    return EngineOptions("remote", selection.remote_model, selection.remote_voice, selection.remote_speed, base_url,
                         key, service.timeout, config.network.proxy_url(), service.protocol,
                         selection.instructions, selection.emotion)


def pcm_wav(samples: bytes, sample_rate: int) -> AudioClip:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples)
    return AudioClip(data=output.getvalue())


def _melo_wav(samples: Sequence[float], sample_rate: int) -> AudioClip:
    """Apply one bounded gain to the whole clip and soften its outer edges."""
    import numpy as np

    signal = np.array(samples, dtype=np.float32, copy=True)
    if signal.ndim != 1 or not signal.size or not np.isfinite(signal).all():
        raise ValueError("invalid_audio")
    peak = float(np.max(np.abs(signal)))
    if peak:
        # One gain preserves relative dynamics across every clause in the clip.
        signal *= min(8.0, 0.95 / peak)
    fade = min(int(sample_rate * 0.012), signal.size // 2)
    if fade:
        ramp = np.arange(fade, dtype=np.float32) / fade
        signal[:fade] *= ramp
        signal[-fade:] *= ramp[::-1]
    return pcm_wav((np.clip(signal, -1, 1) * 32767).astype("<i2").tobytes(), sample_rate)


def complete_provider_wav(data: bytes, protocol: str = "openai") -> AudioClip:
    """Finalize streaming RIFF sentinels only after the full bounded response ends."""
    sentinels = {0xFFFFFFFF: 0xFFFFFFFF}
    if protocol == "dashscope":
        # Observed on the complete Qwen-TTS OSS download, including non-streaming requests.
        sentinels[0x7FFFFFBF] = 0x7FFFFF9B
    container_size = int.from_bytes(data[4:8], "little")
    if len(data) >= 44 and data[:4] == b"RIFF" and container_size in sentinels and data[8:12] == b"WAVE":
        result = bytearray(data)
        offset = 12
        while offset + 8 <= len(result):
            size = int.from_bytes(result[offset + 4:offset + 8], "little")
            if result[offset:offset + 4] == b"data" and size == sentinels[container_size]:
                result[offset + 4:offset + 8] = (len(result) - offset - 8).to_bytes(4, "little")
                result[4:8] = (len(result) - 8).to_bytes(4, "little")
                return AudioClip(data=bytes(result))
            offset += 8 + size + size % 2
    return AudioClip(data=data)


class TTSEngine:
    def __init__(self, models: TTSModelStore) -> None:
        self.models = models
        self._local = None
        self._local_model: str | None = None
        self._lock = asyncio.Lock()

    def unload(self) -> None:
        self._local = None
        self._local_model = None

    def unload_if_idle(self, model_id: str) -> None:
        # A different model may be loading on the inference thread. It releases
        # the previous model itself; never mutate its cache from the API thread.
        if not self._lock.locked() and self._local_model == model_id:
            self.unload()

    async def synthesize(self, text: str, options: EngineOptions, cancellation: threading.Event) -> AudioClip:
        async with self._lock:
            if cancellation.is_set():
                raise ValueError("cancelled")
            if options.engine == "remote":
                return await asyncio.wait_for(self._remote(text, options, cancellation), timeout=options.timeout)
            manager = self.models.get(options.model)
            manager.in_use = True
            try:
                # Do not cancel this thread: ownership stays held until inference returns.
                return await asyncio.to_thread(self._local_synthesize, text, options, cancellation)
            finally:
                manager.in_use = False

    def _local_synthesize(self, text: str, options: EngineOptions, cancellation: threading.Event) -> AudioClip:
        import numpy as np
        if self._local_model != options.model:
            self.unload()
        if self._local is None:
            manager = self.models.get(options.model)
            manager.verify()
            root = manager.directory
            if options.model == MELO_ID:
                try:
                    import sherpa_onnx
                except ImportError as exc:
                    raise ValueError("runtime_missing") from exc
                model = sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(root / "model.onnx"), tokens=str(root / "tokens.txt"),
                        lexicon=str(root / "lexicon.txt"), noise_scale=0.667, noise_scale_w=0.8),
                    num_threads=2, provider="cpu")
                rules = ("date.fst", "phone.fst", "number.fst")
                config = sherpa_onnx.OfflineTtsConfig(
                    model=model, rule_fsts=",".join(str(root / name) for name in rules),
                    # Melo treats commas as sentence boundaries. Synthesize the
                    # service's bounded segment together to retain prosody.
                    max_num_sentences=0,
                )
                if not config.validate():
                    raise ValueError("model_invalid")
                self._local = sherpa_onnx.OfflineTts(config)
            else:
                try:
                    from .kokoro import KokoroTts, validate_kokoro_runtime

                    validate_kokoro_runtime()
                    self._local = KokoroTts(root)
                except (ImportError, OSError) as exc:
                    raise ValueError("runtime_missing") from exc
            self._local_model = options.model
        if cancellation.is_set():
            raise ValueError("cancelled")
        if options.model == MELO_ID:
            audio = self._local.generate(text, sid=0, speed=options.speed,
                                         callback=lambda *_: 0 if cancellation.is_set() else 1)
        else:
            audio = self._local.generate(text, sid=VOICE_NAMES.index(options.voice), speed=options.speed,
                                         cancellation=cancellation)
        if cancellation.is_set():
            raise ValueError("cancelled")
        if options.model == MELO_ID:
            return _melo_wav(audio.samples, audio.sample_rate)
        samples = (np.clip(audio.samples, -1, 1) * 32767).astype("<i2").tobytes()
        return pcm_wav(samples, audio.sample_rate)

    async def _remote(self, text: str, options: EngineOptions, cancellation: threading.Event) -> AudioClip:
        headers = {"Authorization": f"Bearer {options.api_key}"} if options.api_key else {}
        path = "/audio/speech"
        payload = {"model": options.model, "voice": options.voice, "input": text,
                   "speed": options.speed, "response_format": "wav"}
        if options.instructions:
            payload["instructions"] = options.instructions
        if options.protocol == "minimax":
            path = "/t2a_v2"
            voice = {"voice_id": options.voice, "speed": options.speed, "vol": 1, "pitch": 0}
            if options.emotion:
                voice["emotion"] = options.emotion
            payload = {"model": options.model, "text": text, "stream": False, "output_format": "hex",
                       "voice_setting": voice, "audio_setting": {"format": "wav", "sample_rate": 24000, "channel": 1}}
        elif options.protocol == "dashscope":
            path = "/services/aigc/multimodal-generation/generation"
            inputs = {"text": text, "voice": options.voice, "language_type": "Auto"}
            if options.instructions:
                inputs["instructions"] = options.instructions
            payload = {"model": options.model, "input": inputs}
        async with httpx.AsyncClient(timeout=options.timeout, follow_redirects=False,
                                     proxy=options.proxy_url, trust_env=False) as client:
            async with client.stream("POST", options.base_url.rstrip("/") + path,
                                     headers=headers, json=payload) as response:
                limit = 5 * 1024 * 1024 if options.protocol == "minimax" else 2 * 1024 * 1024
                data = await bounded_response(response, cancellation, limit)
            if options.protocol == "minimax":
                try:
                    result = json.loads(data)
                    if result["base_resp"]["status_code"] != 0:
                        raise ValueError("provider_rejected")
                    if result["data"]["status"] != 2 or not isinstance(result["data"]["audio"], str):
                        raise ValueError("provider_invalid_response")
                    data = bytes.fromhex(result["data"]["audio"])
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("provider_invalid_response") from exc
            elif options.protocol == "dashscope":
                try:
                    result = json.loads(data)
                    if result.get("code") or result.get("output", {}).get("finish_reason") != "stop":
                        raise ValueError("provider_rejected")
                    url = dashscope_audio_url(result["output"]["audio"]["url"])
                except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                    raise ValueError("provider_invalid_response") from exc
                # Signed resource URLs never receive the provider credential and never redirect.
                async with client.stream("GET", url) as response:
                    data = await bounded_response(response, cancellation, 2 * 1024 * 1024)
        if cancellation.is_set():
            raise ValueError("cancelled")
        return complete_provider_wav(data, options.protocol)


async def bounded_response(response: httpx.Response, cancellation: threading.Event, limit: int) -> bytes:
    if response.status_code != 200:
        raise ValueError("provider_rejected")
    data = bytearray()
    async for chunk in response.aiter_bytes(64 * 1024):
        if cancellation.is_set():
            raise ValueError("cancelled")
        data.extend(chunk)
        if len(data) > limit:
            raise ValueError("audio_too_large")
    return bytes(data)


def dashscope_audio_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("provider_invalid_response")
    url = urlsplit(value)
    allowed = {"dashscope-result-bj.oss-cn-beijing.aliyuncs.com",
               "dashscope-result-wlcb.oss-cn-wulanchabu.aliyuncs.com",
               "dashscope-result-sg.oss-ap-southeast-1.aliyuncs.com"}
    if (url.scheme not in {"http", "https"} or url.hostname not in allowed or url.username or url.password
            or url.port not in {None, 443} or url.fragment):
        raise ValueError("provider_invalid_response")
    return url._replace(scheme="https").geturl()
