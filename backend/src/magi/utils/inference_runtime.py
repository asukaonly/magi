"""Validate the native inference APIs shipped with every service bundle."""

from __future__ import annotations

import importlib


def validate_inference_runtime() -> None:
    """Load native APIs without downloading models or starting a service."""
    required_apis = {
        "onnxruntime": ("InferenceSession", "SessionOptions"),
        "tokenizers": ("Tokenizer",),
        "sherpa_onnx": ("OfflineRecognizer", "OfflineTts"),
    }
    for module_name, names in required_apis.items():
        try:
            module = importlib.import_module(module_name)
            for name in names:
                if not callable(getattr(module, name)):
                    raise ImportError(f"{module_name}.{name} is not available")
        except (ImportError, OSError, AttributeError) as exc:
            raise RuntimeError(
                f"Required inference runtime {module_name} could not be loaded. "
                "Reinstall backend dependencies with the build interpreter and rebuild "
                "the service bundle; model downloads cannot repair missing native libraries."
            ) from exc
