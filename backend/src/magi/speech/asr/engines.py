"""Local Paraformer and OpenAI file-transcription adapters."""

from __future__ import annotations

import io
import json
import wave
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ...config.models import AppConfig
from .catalog import MODEL_ID
from .contracts import ASRError, TranscriptResult


@dataclass(frozen=True)
class ASROptions:
    mode: str
    model: str
    language: str
    endpoint: str = ""
    api_key: str = field(default="", repr=False)
    provider_name: str | None = None
    timeout: int = 90


def resolve_options(config: AppConfig) -> ASROptions:
    settings = config.speech.asr
    if not settings.enabled:
        raise ASRError("asr_disabled", 409)
    if settings.mode == "local":
        if settings.local_model_id != MODEL_ID:
            raise ASRError("unknown_model", 422)
        if settings.language != "auto":
            raise ASRError("language_unsupported", 422)
        return ASROptions("local", MODEL_ID, "auto")
    provider = config.llm.providers.get(settings.provider_id)
    if provider is None or not provider.enabled or not provider.services.asr.enabled:
        raise ASRError("provider_not_configured", 409)
    service = provider.services.asr
    endpoint = (service.base_url or provider.base_url or "").strip().rstrip("/")
    if not endpoint and provider.provider_type.value == "openai":
        endpoint = "https://api.openai.com/v1"
    url = urlsplit(endpoint)
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ASRError("provider_not_configured", 409)
    if not service.model or not service.model.strip():
        raise ASRError("provider_not_configured", 409)
    return ASROptions(
        "remote",
        service.model.strip(),
        settings.language,
        endpoint + "/audio/transcriptions",
        service.api_key or provider.api_key or "",
        provider.display_name,
        service.timeout,
    )


class LocalASREngine:
    """One recognizer, called serially by its owning service."""

    def __init__(self) -> None:
        self.recognizer = None

    def unload(self) -> None:
        self.recognizer = None

    def transcribe(self, audio: bytes, directory: Path, options: ASROptions) -> TranscriptResult:
        import numpy as np

        try:
            import sherpa_onnx
        except ImportError as exc:
            raise ASRError("runtime_unavailable", 503) from exc
        if self.recognizer is None:
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=str(directory / "model.int8.onnx"),
                tokens=str(directory / "tokens.txt"),
                num_threads=2,
                sample_rate=16000,
                feature_dim=80,
                decoding_method="greedy_search",
                debug=False,
                provider="cpu",
            )
        with wave.open(io.BytesIO(audio), "rb") as source:
            samples = (
                np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(
                    np.float32
                )
                / 32768
            )
        if not np.any(samples):
            return TranscriptResult(text="", no_speech=True, engine="local", model=options.model)
        stream = self.recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        self.recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        return TranscriptResult(text=text, no_speech=not text, engine="local", model=options.model)


async def remote_transcribe(audio: bytes, options: ASROptions) -> TranscriptResult:
    headers = {"Authorization": f"Bearer {options.api_key}"} if options.api_key else {}
    fields = {"model": options.model, "response_format": "json"}
    if options.language != "auto":
        fields["language"] = options.language
    try:
        # No redirects or retries: neither credentials nor paid requests are replayed.
        async with httpx.AsyncClient(timeout=options.timeout, follow_redirects=False) as client:
            async with client.stream(
                "POST",
                options.endpoint,
                headers=headers,
                data=fields,
                files={"file": ("recording.wav", audio, "audio/wav")},
            ) as response:
                if response.status_code in (401, 403):
                    raise ASRError("provider_auth_failed", 502)
                if response.status_code == 429:
                    raise ASRError("provider_busy", 503)
                if response.status_code >= 300:
                    raise ASRError("provider_rejected", 502)
                body = bytearray()
                async for chunk in response.aiter_bytes(8192):
                    body.extend(chunk)
                    if len(body) > 128 * 1024:
                        raise ASRError("provider_invalid_response", 502)
        value = json.loads(body)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("text"), str)
            or len(value["text"]) > 16000
        ):
            raise ASRError("provider_invalid_response", 502)
        text = value["text"].strip()
        language = value.get("language")
        if language is not None and (not isinstance(language, str) or len(language) > 128):
            raise ASRError("provider_invalid_response", 502)
        return TranscriptResult(
            text=text, language=language, no_speech=not text, engine="remote", model=options.model
        )
    except httpx.TimeoutException as exc:
        raise ASRError("provider_timeout", 504) from exc
    except httpx.HTTPError as exc:
        raise ASRError("provider_unavailable", 502) from exc
    except (ValueError, UnicodeError) as exc:
        raise ASRError("provider_invalid_response", 502) from exc
