"""Validate the native inference APIs shipped with every service bundle."""

from __future__ import annotations

import importlib


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
        from magi.speech.tts.kokoro import validate_kokoro_runtime

        validate_kokoro_runtime()
    except (ImportError, OSError, ValueError, RuntimeError, AttributeError) as exc:
        raise RuntimeError("Required inference runtime espeakng_loader could not convert text. Rebuild the service bundle.") from exc
