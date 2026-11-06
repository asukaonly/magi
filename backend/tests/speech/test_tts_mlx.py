"""Complete-WAV and cancellation invariants independent of Metal hardware."""

import io
import threading
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from magi.config.models import AppConfig
from magi.speech.tts.engines import resolve_options
from magi.speech.tts.mlx import MLXTTS
from magi.speech.tts.models import VOX_ID


def adapter(audio, *, tokens=10):
    engine = MLXTTS.__new__(MLXTTS)
    engine.model_id = VOX_ID
    engine.mx = SimpleNamespace(eval=Mock(), random=SimpleNamespace(seed=Mock()))
    engine.model = Mock()
    engine.model.generate.return_value = iter([SimpleNamespace(audio=audio, sample_rate=48000, token_count=tokens)])
    return engine


def test_stereo_is_averaged_and_clip_uses_one_gain():
    engine = adapter(np.array([[0.25, 0.75], [-1.5, -2.5], [0.5, 0.5]], dtype=np.float32))
    result = engine.generate("Hello", resolve_options(AppConfig()), None, threading.Event())
    with wave.open(io.BytesIO(result.data)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 48000
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2") / 32767
    np.testing.assert_allclose(samples, [0.245, -0.98, 0.245], atol=1 / 32767)
    assert engine.model.generate.call_args.kwargs["stream"] is False


@pytest.mark.parametrize(("audio", "tokens", "code"), [
    (np.array([np.nan]), 10, "invalid_audio"),
    (np.zeros(1024 * 1024), 10, "audio_too_large"),
    (np.ones(10), 500, "generation_limit"),
])
def test_invalid_or_truncated_generation_is_never_published(audio, tokens, code):
    with pytest.raises(ValueError, match=code):
        adapter(audio, tokens=tokens).generate("Hello", resolve_options(AppConfig()), None, threading.Event())


def test_cancelled_native_result_is_discarded():
    engine = adapter(np.ones(10))
    cancellation = threading.Event()

    def generate(**kwargs):
        cancellation.set()
        yield SimpleNamespace(audio=np.ones(10), sample_rate=48000, token_count=10)

    engine.model.generate.side_effect = generate
    with pytest.raises(ValueError, match="cancelled"):
        engine.generate("Hello", resolve_options(AppConfig()), None, cancellation)
