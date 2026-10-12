"""Waveform invariants and opt-in real-model coverage for speech continuity."""

import io
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from magi.speech.tts.engines import EngineOptions, TTSEngine, _melo_wav
from magi.speech.tts.models import MELO_ID, TTSModelStore
from magi.speech.tts.text import clean_segments


def read_samples(clip):
    with wave.open(io.BytesIO(clip.data)) as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2") / 32767, wav.getframerate()


def test_clip_gain_preserves_clause_dynamics_and_only_fades_outer_edges():
    source = np.r_[np.full(1000, 0.05), np.full(1000, -0.2)]
    original = source.copy()
    samples, rate = read_samples(_melo_wav(source, 24000))
    assert rate == 24000 and len(samples) == len(source)
    assert np.array_equal(source, original)
    assert samples[0] == samples[-1] == 0
    assert samples[500] == pytest.approx(0.2375, abs=1 / 32767)
    assert samples[1500] == pytest.approx(-0.95, abs=1 / 32767)
    # The clause boundary is neither faded nor independently normalized.
    assert samples[999] == samples[500]
    assert samples[1000] == samples[1500]


@pytest.mark.parametrize("amplitude,expected", [(0.001, 0.008), (0.2, 0.95), (2, 0.95)])
def test_gain_caps_quiet_amplification_and_prevents_clipping(amplitude, expected):
    samples, _ = read_samples(_melo_wav([amplitude] * 1000, 16000))
    assert max(samples) == pytest.approx(expected, abs=1 / 32767)
    assert np.isfinite(samples).all()


@pytest.mark.parametrize("count", [1, 2, 20, 1000])
def test_silence_and_short_clips_keep_their_length(count):
    samples, _ = read_samples(_melo_wav([0.0] * count, 16000))
    assert len(samples) == count and not np.any(samples)


@pytest.mark.parametrize("samples", [[], [float("nan")], [float("inf")], [[0.1]]])
def test_invalid_samples_are_not_published(samples):
    with pytest.raises(ValueError, match="invalid_audio"):
        _melo_wav(samples, 24000)


@pytest.mark.asyncio
async def test_cancellation_during_native_inference_discards_complete_result(tmp_path):
    cancellation = threading.Event()
    engine = TTSEngine(TTSModelStore(tmp_path))

    def generate(_text, *, sid, speed, callback):
        cancellation.set()
        assert callback([0.1] * 1000, 1.0) == 0
        return SimpleNamespace(samples=[0.1] * 1000, sample_rate=44100)

    engine._local_model = MELO_ID
    engine._local = SimpleNamespace(generate=generate)
    with pytest.raises(ValueError, match="cancelled"):
        await engine.synthesize("你好，今天的天气很好。", EngineOptions("local", MELO_ID, "zh_en", 1), cancellation)
    assert not engine.models.get(MELO_ID).in_use


@pytest.mark.skipif(not os.environ.get("MAGI_TTS_TEST_MODELS"), reason="Requires downloaded, verified TTS models")
@pytest.mark.asyncio
@pytest.mark.parametrize("speed", [0.5, 1, 2])
async def test_real_melo_keeps_comma_clauses_in_one_native_generation(monkeypatch, speed):
    import sherpa_onnx

    constructor = sherpa_onnx.OfflineTts
    batches = []

    class ObservedTts:
        def __init__(self, config):
            self.native = constructor(config)

        def generate(self, text, *, sid, speed, callback):
            def observe(samples, progress):
                batches.append(len(samples))
                return callback(samples, progress)
            return self.native.generate(text, sid=sid, speed=speed, callback=observe)

    monkeypatch.setattr(sherpa_onnx, "OfflineTts", ObservedTts)
    engine = TTSEngine(TTSModelStore(Path(os.environ["MAGI_TTS_TEST_MODELS"])))
    text = "你好，今天的天气很好，我们来测试一下语音播放。"
    assert clean_segments(text, max_chars=min(200, max(25, int(80 * speed)))) == [text]
    clip = await engine.synthesize(text, EngineOptions("local", MELO_ID, "zh_en", speed), threading.Event())
    samples, rate = read_samples(clip)
    assert len(batches) == 1
    assert len(samples) == batches[0] and rate == 44100
    assert samples[0] == samples[-1] == 0
    assert np.max(np.abs(samples)) <= 0.951
    assert len(clip.data) <= 2 * 1024 * 1024
