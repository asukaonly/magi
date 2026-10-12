"""Compare real Kokoro clause synthesis with the production continuous adapter.

Usage: python scripts/probe-kokoro-continuity.py TTS_MODELS_DIR OUTPUT_DIR
Requires installed backend dependencies and previously downloaded models.
No downloads, credentials, audio playback or personal settings are used.
"""

import argparse
import asyncio
import io
import json
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "sdk/src")]

GREETING = "你好，今天的天气很好，我们来测试一下语音播放。"
CASES = [
    ("greeting", "zf_xiaobei", GREETING),
    ("greeting_xiaoni", "zf_xiaoni", GREETING),
    ("greeting_xiaoxiao", "zf_xiaoxiao", GREETING),
    ("greeting_male", "zm_yunjian", GREETING),
    ("mixed", "zf_xiaobei", "你好，今天我们测试 API 和 Python，确认中文和 English 能够自然衔接。"),
    ("english", "af_heart", "Hello, the weather is lovely today, and we are testing natural speech."),
    ("long", "zf_xiaobei", "今天我们来测试比较长的中文语音，观察逗号前后的停顿和音量是否自然，随后再继续讲述下一段内容，让整句话保持连贯而不是像剪辑一样突然断开，同时也确认慢速播放时不会丢失任何文字。"),
]


def inspect_wav(data: bytes) -> dict:
    with wave.open(io.BytesIO(data)) as wav:
        rate = wav.getframerate()
        signal = np.frombuffer(wav.readframes(wav.getnframes()), "<i2").astype(float) / 32768
    return {"sample_rate": rate, "seconds": len(signal) / rate,
            "peak": float(np.max(np.abs(signal))), "rms": float(np.sqrt(np.mean(signal ** 2))),
            "clipped_samples": int(np.count_nonzero(np.abs(signal) >= 32767 / 32768))}


async def probe(model_root: Path, output: Path) -> None:
    from magi.speech.tts.engines import EngineOptions, TTSEngine, pcm_wav
    from magi.speech.tts.models import MELO_ID, MODEL_ID, VOICE_NAMES, TTSModelStore

    models = TTSModelStore(model_root)
    models.get(MODEL_ID).verify()
    root = models.get(MODEL_ID).directory
    # Reproduce the previous production configuration only for this comparison.
    baseline = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(root / "model.onnx"), voices=str(root / "voices.bin"),
            tokens=str(root / "tokens.txt"), data_dir=str(root / "espeak-ng-data"),
            lexicon=",".join(str(root / name) for name in ("lexicon-us-en.txt", "lexicon-zh.txt"))),
            num_threads=2, provider="cpu"),
        rule_fsts=",".join(str(root / name) for name in ("date-zh.fst", "phone-zh.fst", "number-zh.fst")),
        max_num_sentences=1, silence_scale=0.2,
    ))
    engine = TTSEngine(models)
    results = []
    for case, voice, text in CASES:
        before_batches = []

        def observe(samples, _progress, frames=before_batches):
            frames.append(len(samples))
            return 1

        start = time.monotonic()
        raw = baseline.generate(text, sid=VOICE_NAMES.index(voice), speed=1, callback=observe)
        before_seconds = time.monotonic() - start
        before = pcm_wav((np.clip(raw.samples, -1, 1) * 32767).astype("<i2").tobytes(), raw.sample_rate)
        start = time.monotonic()
        after = await engine.synthesize(text, EngineOptions("local", MODEL_ID, voice, 1), threading.Event())
        after_seconds = time.monotonic() - start
        (output / f"{case}_before.wav").write_bytes(before.data)
        (output / f"{case}_after.wav").write_bytes(after.data)
        row = {"case": case, "voice": voice, "text": text,
               "before": {**inspect_wav(before.data), "batches": len(before_batches), "inference_seconds": before_seconds},
               "after": {**inspect_wav(after.data), "batches": len(engine._local.token_batches(text)), "inference_seconds": after_seconds}}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if models.get(MELO_ID).directory.is_dir():
        melo = await engine.synthesize(GREETING, EngineOptions("local", MELO_ID, "zh_en", 1), threading.Event())
        (output / "greeting_melo.wav").write_bytes(melo.data)
    (output / "comparison.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    asyncio.run(probe(args.model_root, args.output))
