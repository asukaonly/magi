"""Four pinned MLX speech models behind the existing complete-WAV engine."""

from __future__ import annotations

import gc
import io
import threading
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from magi_plugin_sdk.audio import AudioClip

from .models import VOX_ID, QWEN_ID, NANO_ID

if TYPE_CHECKING:
    from .engines import EngineOptions


class MLXTTS:
    def __init__(self, directory: Path, codec: Path, model_id: str) -> None:
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model

        mx.set_cache_limit(512 * 1024**2)
        mx.set_memory_limit(min(12 * 1024**3, int(mx.device_info()["max_recommended_working_set_size"] * 0.7)))
        self.mx = mx
        self.model_id = model_id
        self.codec = codec
        # The caller verifies all model/tokenizer/codec resources before loading.
        self.model = load_model(directory, strict=True)
        mx.eval(self.model.parameters())
        self.reference_key: str | None = None
        self.reference_codes = None

    def close(self) -> None:
        self.model = None
        self.reference_codes = None
        gc.collect()
        self.mx.clear_cache()

    def generate(self, text: str, options: EngineOptions, reference: Path | None,
                 cancellation: threading.Event) -> AudioClip:
        import numpy as np

        if cancellation.is_set():
            raise ValueError("cancelled")
        mx = self.mx
        mx.random.seed(options.seed)
        kwargs = {"text": text, "stream": False, "max_tokens": 1500}
        if self.model_id == VOX_ID:
            kwargs.update(instruct=options.voice_description or None, ref_audio=str(reference) if reference else None,
                          inference_timesteps=10, cfg_value=2.0, max_tokens=500)
        elif self.model_id == QWEN_ID:
            kwargs.update(voice=options.voice, lang_code="auto", instruct=options.voice_description or None)
        else:
            if self.reference_key != options.reference_audio:
                self.reference_codes = self.model.encode_reference_audio(str(reference), source=str(self.codec)) if reference else None
                self.reference_key = options.reference_audio
            kwargs.update(prompt_audio_codes=self.reference_codes, audio_tokenizer_source=str(self.codec))
            if self.model_id == NANO_ID:
                # Keep the service's bounded clause together instead of splitting on commas again.
                kwargs.update(max_tokens=750, voice_clone_max_text_tokens=256)
        frames = []
        rate = None
        count = 0
        for item in self.model.generate(**kwargs):
            if cancellation.is_set():
                raise ValueError("cancelled")
            mx.eval(item.audio)
            signal = np.asarray(item.audio, dtype=np.float32)
            if signal.ndim == 2 and signal.shape[1] in (1, 2):
                # Speech is delivered as mono; average channels, never flatten stereo samples.
                signal = signal.mean(axis=1)
            if signal.ndim != 1 or not signal.size or not np.isfinite(signal).all():
                raise ValueError("invalid_audio")
            if rate is not None and rate != item.sample_rate:
                raise ValueError("audio_format_changed")
            rate = item.sample_rate
            count += len(signal)
            if count * 2 + 44 > 2 * 1024 * 1024 or count > rate * 60:
                raise ValueError("audio_too_large")
            if item.token_count >= kwargs["max_tokens"]:
                raise ValueError("generation_limit")
            frames.append(signal)
        if cancellation.is_set():
            raise ValueError("cancelled")
        if not frames or rate is None:
            raise ValueError("invalid_audio")
        signal = np.concatenate(frames)
        # Preserve dynamics; only attenuate an over-range clip, with one gain for all samples.
        peak = float(np.max(np.abs(signal)))
        if peak > 1:
            signal *= 0.98 / peak
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(rate)
            writer.writeframes((signal * 32767).astype("<i2").tobytes())
        return AudioClip(data=output.getvalue())
