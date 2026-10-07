"""Recognizer wiring and bounded audio must preserve the complete recording."""

import io
import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from magi.config.speech import ASRSettings
from magi.speech.asr.engines import ASROptions, LocalASREngine, _bounded_segments


def audio(samples):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(samples.astype("<i2").tobytes())
    return buffer.getvalue()


@pytest.mark.parametrize("seconds", [0, 1, 25, 26, 50, 60])
def test_audio_windows_cover_each_sample_once(seconds):
    samples = np.random.default_rng(1).uniform(-1, 1, seconds * 16000).astype(np.float32)
    segments = list(_bounded_segments(samples))
    assert all(0 < len(segment) <= 25 * 16000 for segment in segments)
    actual = np.concatenate(segments) if segments else np.array([], dtype=np.float32)
    np.testing.assert_array_equal(actual, samples)


def test_audio_windows_prefer_a_pause_near_the_limit():
    samples = np.ones(60 * 16000, dtype=np.float32)
    samples[22 * 16000 : 23 * 16000] = 0
    segments = list(_bounded_segments(samples))
    assert 22 * 16000 < len(segments[0]) < 23 * 16000
    np.testing.assert_array_equal(np.concatenate(segments), samples)


@pytest.mark.parametrize("model,method", [
    ("qwen3-asr-0.6b-int8", "from_qwen3_asr"),
    ("whisper-large-v3-turbo-int8", "from_whisper"),
])
def test_autoregressive_engines_decode_the_end_of_a_long_recording(monkeypatch, tmp_path, model, method):
    calls, captured = [], []

    def construct(**kwargs):
        calls.append(kwargs)

        def create_stream():
            return SimpleNamespace(
                accept_waveform=lambda rate, samples: captured.append((rate, samples.copy())),
                result=SimpleNamespace(text=f"part {len(captured) + 1}"),
            )

        return SimpleNamespace(create_stream=create_stream, decode_stream=lambda stream: None)

    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(
        OfflineRecognizer=SimpleNamespace(**{method: construct}),
    ))
    engine = LocalASREngine()
    samples = np.full(60 * 16000, 1000, dtype=np.int16)
    options = ASROptions("local", model, "auto")
    result = engine.transcribe(audio(samples), tmp_path, options)
    assert result.text == "part 1 part 2 part 3"
    assert not result.no_speech
    assert all(rate == 16000 and len(chunk) <= 25 * 16000 for rate, chunk in captured)
    np.testing.assert_array_equal(np.concatenate([chunk for _, chunk in captured]), samples / 32768)
    engine.transcribe(audio(samples[:16000]), tmp_path, options)
    assert len(calls) == 1
    assert calls[0]["provider"] == "cpu" and calls[0]["num_threads"] == 2
    if method == "from_whisper":
        assert calls[0]["encoder"] == str(tmp_path / "turbo-encoder.int8.onnx")
        assert calls[0]["decoder"] == str(tmp_path / "turbo-decoder.int8.onnx")
        assert calls[0]["tokens"] == str(tmp_path / "turbo-tokens.txt")
        assert calls[0]["language"] == "" and calls[0]["task"] == "transcribe"
    else:
        assert calls[0]["tokenizer"] == str(tmp_path / "tokenizer")
        assert calls[0]["conv_frontend"] == str(tmp_path / "conv_frontend.onnx")
        assert calls[0]["encoder"] == str(tmp_path / "encoder.int8.onnx")
        assert calls[0]["decoder"] == str(tmp_path / "decoder.int8.onnx")
        assert calls[0]["max_new_tokens"] == 512
        assert calls[0]["max_total_len"] == 1024
    engine.unload()
    assert engine.recognizer is None and engine.model_id is None


@pytest.mark.parametrize("model,method", [
    ("qwen3-asr-0.6b-int8", "from_qwen3_asr"),
    ("whisper-large-v3-turbo-int8", "from_whisper"),
])
def test_silent_audio_never_enters_autoregressive_decoding(monkeypatch, tmp_path, model, method):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(
        OfflineRecognizer=SimpleNamespace(**{method: lambda **kwargs: object()}),
    ))
    result = LocalASREngine().transcribe(
        audio(np.zeros(60 * 16000)), tmp_path, ASROptions("local", model, "auto"),
    )
    assert result.no_speech and result.text == ""


def test_new_default_does_not_replace_an_explicit_model():
    assert ASRSettings().local_model_id == "sensevoice-zh-en-ja-ko-yue"
    assert ASRSettings(local_model_id="paraformer-zh-en-fp32").local_model_id == "paraformer-zh-en-fp32"
