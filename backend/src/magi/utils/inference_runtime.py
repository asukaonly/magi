"""Validate the native inference APIs shipped with every service bundle."""

from __future__ import annotations

import importlib
import json
import platform
import tempfile
from pathlib import Path

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
    if "transformers" in required_apis:
        _check_catalog_tokenizers()
    try:
        if not english_phonemes("Hello"):
            raise ValueError("runtime_missing")
    except (ImportError, OSError, ValueError, RuntimeError, AttributeError) as exc:
        raise RuntimeError("Required inference runtime espeakng_loader could not convert text. Rebuild the service bundle.") from exc


def _check_catalog_tokenizers() -> None:
    """Exercise the catalog's lazy tokenizer lookup without fetching model weights."""
    from tokenizers import Tokenizer
    from tokenizers.models import BPE
    from transformers import AutoTokenizer

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tokenizer = Tokenizer(BPE({"h": 0, "e": 1, "l": 2, "o": 3}, merges=[]))
        tokenizer.save(str(root / "tokenizer.json"))
        for name in ("LlamaTokenizer", "Qwen2Tokenizer"):
            (root / "tokenizer_config.json").write_text(
                json.dumps({"tokenizer_class": name}), encoding="utf-8"
            )
            loaded = AutoTokenizer.from_pretrained(root, local_files_only=True)
            ids = loaded.encode("hello", add_special_tokens=False)
            if type(loaded).__name__ != name or ids != [0, 1, 2, 2, 3]:
                raise RuntimeError(f"Packaged {name} failed the offline tokenizer check")
