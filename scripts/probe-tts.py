#!/usr/bin/env python3
"""Run real local TTS probes or serve an isolated loopback test API.

Usage: PYTHONPATH=backend/src:sdk/src python scripts/probe-tts.py MODEL_DIR OUTPUT_DIR [--serve]
The API mode is a development probe, never a production gateway substitute.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "sdk/src")]

ZH = [
    "你好，这是 Magi 的本地语音试听。", "今天阳光很好，我们一起出去走走。",
    "请在会议开始之前检查麦克风。", "模型运行在连接的服务所在机器上。",
    "保存设置后，点击试听按钮。", "如果下载失败，请检查网络后重试。",
    "你可以随时暂停、继续或者停止朗读。", "文字回答不会因为语音失败而丢失。",
    "中文的标点符号应该产生自然停顿。", "这条消息用于验证长句分段的边界。",
    "桌面切换会话后，旧音频不应继续播放。", "我们没有把推理和投送合并在一起。",
    "请确认明天的航班时间和登机口。", "账单金额是一千二百三十四元五角六分。",
    "十月二日下午三点半在二号会议室见。", "凌晨零点整，新的日期开始了。",
    "服务器正在忙碌，请稍后再试。", "只包含代码的消息没有可朗读正文。",
    "语音生成成功，并不表示扬声器已经播放。", "谢谢你使用本地语音功能，再见。",
]
EN = [
    "Hello, this is a local speech synthesis test.", "Please check the microphone before the meeting.",
    "The model runs on the machine hosting the service.", "You can pause, resume, or stop playback.",
    "A failed audio request does not change the written answer.", "This file contains a complete audio segment.",
    "The next sentence should follow the previous one.", "No private message is sent to a remote provider in local mode.",
    "The account balance is one thousand dollars.", "Thank you for testing speech playback.",
]
MIXED = [
    "今天是2026年10月2日，Magi is ready.", "会议开始时间是15:30，please be on time.",
    "这次购买了3个苹果和2个橙子，thank you.", "版本号是1.13.8，please check the settings.",
    "Hello，欢迎来到上海。", "OpenAI 和 Kokoro 使用不同的音色标识。",
    "总计1234.56元，payment received.", "请打开 Settings，然后选择语音播报。",
    "CPU 使用率为50%，the server is busy.", "明天早上9点见，see you tomorrow.",
]


def prepare(args):
    from magi.config.models import AppConfig
    from magi.speech.tts.models import TTSModelStore, local_voices
    from magi.speech.tts.service import SynthesisService
    from magi.utils.runtime import set_runtime_dir

    set_runtime_dir(args.output_dir / "runtime")
    config = AppConfig()
    config.speech.tts.local_model = args.model_id or args.model_dir.name
    voices = local_voices(config.speech.tts.local_model)
    config.speech.tts.local_voice = next((voice.id for voice in voices if voice.id == "zf_xiaobei"), voices[0].id if voices else "")
    config.speech.tts.local_model_path = str(args.model_dir.resolve())
    config.speech.tts.local_codec_path = str(args.codec_dir.resolve()) if args.codec_dir else ""
    config.speech.tts.voice_description = args.description
    async def no_messages(_source):
        raise ValueError("not_found")
    service = SynthesisService(args.output_dir / "receipts", TTSModelStore(args.output_dir / "models"), no_messages)
    if args.reference:
        reference = service.references.add(args.reference.read_bytes(), args.reference.name)
        config.speech.tts.reference_audio = reference.id
    return config, service


async def probe(args) -> None:
    import resource
    from dataclasses import asdict

    from magi.speech.tts.engines import resolve_options
    from magi_plugin_sdk.audio import inspect_wav

    config, service = prepare(args)
    options = resolve_options(config)
    rows = [(lang, text) for lang, texts in (("zh", ZH), ("en", EN), ("mixed", MIXED)) for text in texts]
    if args.quick:
        rows = [("zh", "你好，今天的天气很好。这是一段语音合成测试。"),
                ("en", "Hello, this is a local speech test."), ("mixed", "今天下午三点开会，please be on time.")]
    results = []
    for index, (language, text) in enumerate(rows):
        started = time.monotonic()
        clip = await service.synthesize_delivery(text, options)
        elapsed = time.monotonic() - started
        info = inspect_wav(clip.data)
        (args.output_dir / f"{index:02d}-{language}.wav").write_bytes(clip.data)
        row = {"index": index, "language": language, "text": text, "generation_seconds": elapsed,
               "bytes": len(clip.data), "audio": asdict(info), "rtf": elapsed / info.duration_seconds,
               "process_peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "listening_review": "pending"}
        results.append(row)
        (args.output_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(json.dumps(row, ensure_ascii=False), flush=True)
    service.engine.unload()


def serve(args) -> None:
    import uvicorn
    from fastapi import FastAPI
    from magi.api.routers import tts
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
    from magi.bootstrap import speech_runtime
    from magi.config.tts import TTSSettings

    config, service = prepare(args)
    speech_runtime._service = service
    tts.get_config = lambda: config
    def save(values):
        config.speech.tts = TTSSettings.model_validate(values["speech.tts"])
        return True
    tts.save_config = save
    app = FastAPI()
    app.include_router(_build_public_router(tts.tts_router, _PUBLIC_ROUTE_METHODS["tts"]), prefix="/api/speech/tts")
    print("Isolated probe API on loopback port 5190; not a production authentication boundary.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=5190, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--model-id")
    parser.add_argument("--codec-dir", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--description", default="")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Keep logging/config bootstrap separate from personal runtime data.
    os.environ["MAGI_HOME"] = str(args.output_dir / "runtime")
    if args.serve:
        serve(args)
    else:
        asyncio.run(probe(args))
