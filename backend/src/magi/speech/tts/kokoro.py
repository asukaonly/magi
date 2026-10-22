"""Bounded Kokoro inference that keeps comma clauses in the same context."""

from dataclasses import dataclass
from pathlib import Path
import re
import threading

import numpy as np
from numpy.typing import NDArray

from magi.utils.espeak import english_phonemes

_PUNCTUATION = str.maketrans("，。！？；：、（）", ",.!?;:,()")
_MARKS = frozenset(",.!?;:—…\"()“”")


def validate_kokoro_runtime() -> None:
    """Load the packaged phonemizer and verify an actual native conversion."""
    if not english_phonemes("Hello"):
        raise ValueError("runtime_missing")


@dataclass(frozen=True)
class KokoroAudio:
    samples: NDArray[np.float32]
    sample_rate: int = 24000


def trim_outer_silence(samples: NDArray[np.float32], sample_rate: int) -> NDArray[np.float32]:
    """Keep inner pauses and amplitude; trim only quiet outer padding."""
    signal = np.array(samples, dtype=np.float32, copy=True)
    if signal.ndim != 1 or not signal.size or not np.isfinite(signal).all():
        raise ValueError("invalid_audio")
    active = np.flatnonzero(np.abs(signal) > 0.001)
    if active.size:
        padding = int(sample_rate * 0.08)
        signal = signal[max(0, active[0] - padding):min(len(signal), active[-1] + padding + 1)]
    fade = min(int(sample_rate * 0.005), len(signal) // 2)
    if fade:
        ramp = np.arange(fade, dtype=np.float32) / fade
        signal[:fade] *= ramp
        signal[-fade:] *= ramp[::-1]
    return signal


class KokoroTts:
    """Use the pinned ONNX model, lexicon and number/date/phone normalizers."""

    def __init__(self, root: Path) -> None:
        import kaldifst
        import onnxruntime as ort

        self.vocab = {symbol: int(index) for line in (root / "tokens.txt").read_text(encoding="utf-8").splitlines()
                      for symbol, index in [line.rsplit(" ", 1)]}
        self.lexicon = {}
        for line in (root / "lexicon-zh.txt").read_text(encoding="utf-8").splitlines():
            word, *phonemes = line.split()
            self.lexicon[word] = [self.vocab[p] for p in phonemes]
        self.normalizers = [kaldifst.TextNormalizer(str(root / name))
                            for name in ("date-zh.fst", "phone-zh.fst", "number-zh.fst")]
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(root / "model.onnx"), options, providers=["CPUExecutionProvider"])
        metadata = self.session.get_modelmeta().custom_metadata_map
        if (metadata.get("model_type") != "kokoro" or metadata.get("style_dim") != "510,1,256"
                or metadata.get("sample_rate") != "24000" or metadata.get("n_speakers") != "54"):
            raise ValueError("model_invalid")
        self.styles = np.fromfile(root / "voices.bin", dtype="<f4").reshape(54, 510, 256)
        self.sample_rate = 24000

    def token_batches(self, text: str) -> list[list[int]]:
        """Preserve punctuation; split only when the model's 510-token limit requires it."""
        import jieba

        for normalizer in self.normalizers:
            text = normalizer.normalize(text)
        text = re.sub(r"([,.!?;:])", r"\1 ", text.translate(_PUNCTUATION))
        text = re.sub(r"\s+", " ", text).strip()
        tokens: list[int] = []
        word_ends: set[int] = set()
        punctuation_ends: set[int] = set()
        for part in re.findall(r"[\u4e00-\u9fff]+|[^\u4e00-\u9fff]+", text):
            if "\u4e00" <= part[0] <= "\u9fff":
                # Match the official Chinese frontend's word spacing, including
                # no trailing space before punctuation. Its placement affects
                # predicted phoneme durations throughout the sentence.
                for index, word in enumerate(jieba.lcut(part)):
                    if index:
                        tokens.append(self.vocab[" "])
                    offset = 0
                    while offset < len(word):
                        for size in range(min(10, len(word) - offset), 0, -1):
                            phrase = word[offset:offset + size]
                            if phrase in self.lexicon:
                                tokens.extend(self.lexicon[phrase])
                                offset += size
                                break
                        else:
                            raise ValueError("unsupported_text")
                    word_ends.add(len(tokens))
            else:
                # Keep punctuation outside eSpeak so its clause terminators
                # cannot erase the model's comma/period tokens.
                for phrase in re.split(r'([,.!?;:—…"()“”])', part):
                    if phrase in _MARKS:
                        tokens.append(self.vocab[phrase])
                        punctuation_ends.add(len(tokens))
                    elif phrase.strip():
                        if phrase[0].isspace():
                            tokens.append(self.vocab[" "])
                        phonemes = english_phonemes(phrase)
                        for phoneme in phonemes:
                            if phoneme in self.vocab:
                                tokens.append(self.vocab[phoneme])
                            if phoneme.isspace():
                                word_ends.add(len(tokens))
                        word_ends.add(len(tokens))
                        if phrase[-1].isspace():
                            tokens.append(self.vocab[" "])
                    elif phrase:
                        tokens.append(self.vocab[" "])
                        word_ends.add(len(tokens))
        if not tokens:
            raise ValueError("invalid_audio")
        batches = []
        start = 0
        while start < len(tokens):
            end = min(start + 508, len(tokens))  # Two outer padding tokens.
            if end < len(tokens):
                boundaries = [i for i in punctuation_ends if start < i <= end]
                if not boundaries:
                    boundaries = [i for i in word_ends if start < i <= end]
                end = max(boundaries, default=end)
            batches.append(tokens[start:end])
            start = end
        return batches

    def generate(self, text: str, *, sid: int, speed: float,
                 cancellation: threading.Event) -> KokoroAudio:
        if not 0 <= sid < len(self.styles) or not 0.5 <= speed <= 2:
            raise ValueError("invalid_model")
        batches = self.token_batches(text)
        parts = []
        for tokens in batches:
            if cancellation.is_set():
                raise ValueError("cancelled")
            samples = self.session.run(["audio"], {
                "tokens": np.array([[0, *tokens, 0]], dtype=np.int64),
                # Official Kokoro selects style row phoneme_count - 1.
                "style": self.styles[sid, len(tokens) - 1].reshape(1, 256),
                "speed": np.array([speed], dtype=np.float32),
            })[0]
            if cancellation.is_set():
                raise ValueError("cancelled")
            samples = trim_outer_silence(samples, self.sample_rate)
            parts.append(samples)
        signal = np.concatenate(parts) if parts else np.empty(0, dtype=np.float32)
        # No amplification or per-clause normalization. Only attenuate a whole
        # clip that would otherwise clip during PCM conversion.
        peak = float(np.max(np.abs(signal))) if signal.size else 0
        if peak > 1:
            signal *= 0.95 / peak
        return KokoroAudio(signal)
