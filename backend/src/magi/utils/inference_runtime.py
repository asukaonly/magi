"""Validate the native inference APIs shipped with every service bundle."""

from __future__ import annotations

import importlib
import platform

from .espeak import english_phonemes


def validate_inference_runtime() -> None:
    """Load native APIs without downloading models or starting a service."""
    required_apis = {
        "onnxruntime": ("InferenceSession", "SessionOptions"),
        "tokenizers": ("Tokenizer",),
        "kaldifst": ("TextNormalizer",),
        "espeakng_loader": ("get_library_path", "get_data_path"),
        "sherpa_onnx": (
            "OfflineRecognizer",
            "OfflineTts",
            "OfflineRecognizer.from_paraformer",
            "OfflineRecognizer.from_sense_voice",
            "OfflineRecognizer.from_qwen3_asr",
            "OfflineRecognizer.from_whisper",
        ),
    }
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        required_apis.update({
            "mlx.core": ("array", "eval", "set_memory_limit"),
            "mlx_audio.tts.models.voxcpm2": ("Model",),
            "mlx_audio.tts.models.qwen3_tts": ("Model",),
            "mlx_audio.tts.models.moss_tts_nano": ("Model",),
            "mlx_audio.tts.models.moss_tts": ("Model",),
            "mlx_audio.codec": ("MossAudioTokenizer",),
            "transformers": ("AutoTokenizer.from_pretrained",),
        })
    for module_name, names in required_apis.items():
        try:
            module = importlib.import_module(module_name)
            for name in names:
                api = module
                for component in name.split("."):
                    api = getattr(api, component)
                if not callable(api):
                    raise ImportError(f"{module_name}.{name} is not available")
        except (ImportError, OSError, AttributeError) as exc:
            raise RuntimeError(
                f"Required inference runtime {module_name} could not be loaded. "
                "Reinstall backend dependencies with the build interpreter and rebuild "
                "the service bundle; model downloads cannot repair missing native libraries."
            ) from exc
    try:
        if not english_phonemes("Hello"):
            raise ValueError("runtime_missing")
    except (ImportError, OSError, ValueError, RuntimeError, AttributeError) as exc:
        raise RuntimeError("Required inference runtime espeakng_loader could not convert text. Rebuild the service bundle.") from exc
