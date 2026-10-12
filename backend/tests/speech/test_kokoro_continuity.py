"""Kokoro word boundaries, bounded inference and unmodified inner dynamics."""

import io
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from magi.speech.tts import kokoro
from magi.speech.tts.engines import EngineOptions, TTSEngine
from magi.speech.tts.models import MODEL_ID, TTSModelStore


def frontend():
    engine = object.__new__(kokoro.KokoroTts)
    engine.vocab = {c: i + 1 for i, c in enumerate(" ABCDEFGHI,.!?;:—…\"()“”")}
    engine.lexicon = {"你好": [2, 3], "今天": [4, 5], "测": [6], "试": [7]}
    engine.normalizers = []
    return engine


def test_commas_and_word_boundaries_stay_inside_one_inference():
    engine = frontend()
    batches = engine.token_batches("你好，今天测试。")
    space, comma, period = (engine.vocab[c] for c in " ,.")
    assert batches == [[2, 3, comma, space, 4, 5, space, 6, 7, period]]
    # No padding token or space inside the two-syllable test word.
    assert 0 not in batches[0]


def test_mixed_text_keeps_english_words_and_punctuation(monkeypatch):
    engine = frontend()
    monkeypatch.setattr(kokoro, "english_phonemes", lambda text: "H I" if text.strip() == "API Python" else "")
    assert engine.token_batches("你好，API Python 测试。") == [[
        2, 3, engine.vocab[","], engine.vocab[" "], engine.vocab["H"],
        engine.vocab[" "], engine.vocab["I"], engine.vocab[" "], 6, 7, engine.vocab["."],
    ]]


def test_limit_splits_at_punctuation_without_losing_or_reordering_tokens():
    engine = frontend()
    text = ("你好今天测试，" * 90) + "你好。"
    batches = engine.token_batches(text)
    assert len(batches) > 1 and all(0 < len(batch) <= 508 for batch in batches)
    # A normalized comma is followed by one space except at the end of input.
    expected = []
    for _ in range(90):
        expected.extend(engine.token_batches("你好今天测试，")[0] + [engine.vocab[" "]])
    expected.extend(engine.token_batches("你好。")[0])
    assert [token for batch in batches for token in batch] == expected
    assert all(batch[-1] == engine.vocab[","] for batch in batches[:-1])


def test_unrecognized_chinese_is_not_silently_dropped():
    with pytest.raises(ValueError, match="unsupported_text"):
        frontend().token_batches("龘")


def test_outer_trim_keeps_inner_pauses_quiet_speech_and_volume():
    signal = np.r_[np.zeros(1000), np.full(600, 0.02), np.zeros(900),
                   np.full(600, -0.3), np.zeros(1000)].astype(np.float32)
    original = signal.copy()
    result = kokoro.trim_outer_silence(signal, 1000)
    assert np.array_equal(signal, original)
    assert np.array_equal(result[80:-80], signal[1000:-1000])
    assert len(result) == 2260 and result[0] == result[-1] == 0


@pytest.mark.parametrize("signal", [[], [np.nan], [np.inf], [[0.1]]])
def test_invalid_waveform_is_rejected(signal):
    with pytest.raises(ValueError, match="invalid_audio"):
        kokoro.trim_outer_silence(np.array(signal), 24000)


def test_style_index_pcm_rate_and_no_per_batch_gain():
    engine = frontend()
    engine.styles = np.zeros((54, 510, 256), dtype=np.float32)
    engine.styles[45, 2] = 0.3
    engine.sample_rate = 24000
    engine.token_batches = lambda _: [[2, 3, 4]]
    observed = []

    def run(outputs, inputs):
        observed.append(inputs)
        return [np.r_[np.full(2000, 0.02), np.full(2000, -0.3)].astype(np.float32)]

    engine.session = SimpleNamespace(run=run)
    audio = engine.generate("ignored", sid=45, speed=0.5, cancellation=threading.Event())
    assert audio.sample_rate == 24000
    assert observed[0]["tokens"].tolist() == [[0, 2, 3, 4, 0]]
    assert np.all(observed[0]["style"] == np.float32(0.3))
    assert observed[0]["speed"].tolist() == [0.5]
    assert audio.samples[1000] == np.float32(0.02)
    assert audio.samples[3000] == np.float32(-0.3)


@pytest.mark.parametrize("during", [False, True])
def test_cancel_discards_result_and_never_runs_the_next_batch(during):
    engine = frontend()
    engine.styles = np.zeros((54, 510, 256), dtype=np.float32)
    engine.sample_rate = 24000
    engine.token_batches = lambda _: [[2, 3], [4, 5]]
    cancellation = threading.Event()
    observed = []

    def run(*_):
        observed.append(True)
        cancellation.set()
        return [np.ones(1000, dtype=np.float32)]

    engine.session = SimpleNamespace(run=run)
    if not during:
        cancellation.set()
    with pytest.raises(ValueError, match="cancelled"):
        engine.generate("ignored", sid=45, speed=1, cancellation=cancellation)
    assert len(observed) == int(during)


def test_required_english_phonemizer_loads_without_model_downloads():
    result = kokoro.english_phonemes("API Python")
    assert result and "Python" not in result and "aɪ" in result


def test_native_text_cannot_silently_truncate_at_a_null_byte():
    with pytest.raises(ValueError, match="unsupported_text"):
        kokoro.english_phonemes("Hello\x00 world")


@pytest.mark.skipif(not os.environ.get("MAGI_TTS_TEST_MODELS"), reason="Requires downloaded, verified TTS models")
@pytest.mark.asyncio
@pytest.mark.parametrize("speed,voice,text", [
    (0.5, "zf_xiaobei", "你好，今天的天气很好，我们来测试一下语音播放。"),
    (1, "zf_xiaobei", "你好，今天的天气很好，我们来测试一下语音播放。"),
    (2, "zf_xiaobei", "你好，今天的天气很好，我们来测试一下语音播放。"),
    (1, "zm_yunjian", "你好，今天的天气很好，我们来测试一下语音播放。"),
    (1, "zf_xiaoni", "你好，今天我们测试 API 和 Python，确认中文和 English 能够自然衔接。"),
    (1, "af_heart", "Hello, the weather is lovely today, and we are testing natural speech."),
    (1, "zf_xiaobei", "今天是2026年10月12日，电话是13800138000。"),
    (2, "zf_xiaobei", "测试" * 100),
], ids=["slow", "normal", "fast", "male", "mixed", "english", "numbers", "limit"])
async def test_real_kokoro_keeps_bounded_text_together(monkeypatch, speed, voice, text):
    import onnxruntime as ort

    constructor = ort.InferenceSession
    observed = []

    class ObservedSession:
        def __init__(self, *args, **kwargs):
            self.native = constructor(*args, **kwargs)

        def get_modelmeta(self):
            return self.native.get_modelmeta()

        def run(self, names, inputs):
            observed.append(inputs["tokens"].copy())
            return self.native.run(names, inputs)

    monkeypatch.setattr(ort, "InferenceSession", ObservedSession)
    engine = TTSEngine(TTSModelStore(Path(os.environ["MAGI_TTS_TEST_MODELS"])))
    clip = await engine.synthesize(text, EngineOptions("local", MODEL_ID, voice, speed), threading.Event())
    assert len(observed) == (2 if text == "测试" * 100 else 1)
    assert all(len(batch[0]) <= 510 for batch in observed)
    if "今天的天气" in text:
        # Captured from official Misaki 0.9.4 ZHG2P for this fixed sentence.
        phonemes = "ni↓xau↓, ʨi→ntʰjɛ→n tɤ tʰjɛ→nʨʰi↘ xə↓n xau↓, wo↓mən lai↗ ʦʰɤ↘ʂɨ↘ i→ɕja↘ y↓i→n pwo→fa↘ŋ."
        assert observed[0][0].tolist() == [0, *[engine._local.vocab[c] for c in phonemes], 0]
    with wave.open(io.BytesIO(clip.data)) as wav:
        assert wav.getframerate() == 24000 and wav.getnchannels() == 1
        samples = np.frombuffer(wav.readframes(wav.getnframes()), "<i2")
    assert len(clip.data) <= 2 * 1024 * 1024
    assert np.max(np.abs(samples.astype(np.int32))) < 32767
    assert samples[0] == samples[-1] == 0


@pytest.mark.skipif(not os.environ.get("MAGI_TTS_TEST_MODELS"), reason="Requires downloaded, verified TTS models")
@pytest.mark.asyncio
async def test_real_cancel_discards_inflight_audio_before_another_batch(monkeypatch):
    engine = TTSEngine(TTSModelStore(Path(os.environ["MAGI_TTS_TEST_MODELS"])))
    # Warm the exact production instance; cancellation then happens during run.
    await engine.synthesize("你好。", EngineOptions("local", MODEL_ID, "zf_xiaobei", 1), threading.Event())
    cancellation = threading.Event()
    native_run = engine._local.session.run
    calls = []

    def run(names, inputs):
        calls.append(True)
        result = native_run(names, inputs)
        cancellation.set()
        return result

    monkeypatch.setattr(engine._local.session, "run", run)
    with pytest.raises(ValueError, match="cancelled"):
        await engine.synthesize("测试" * 100, EngineOptions("local", MODEL_ID, "zf_xiaobei", 2), cancellation)
    assert len(calls) == 1 and not engine.models.get(MODEL_ID).in_use
