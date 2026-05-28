"""Shared ONNX model variant selection for managed local models.

Both the local embedding loader and the cross-encoder reranker scorer use
the same logic to (1) detect the host platform, (2) pick a variant by
user override or per-platform default, and (3) resolve that variant to a
concrete .onnx path on disk (with a legacy scan-priority fallback for
models that don't declare a ``variants`` block in their registry YAML).

The functions are duck-typed over the registry meta: any dataclass with
``variants: dict[str, T]`` (where each ``T`` has ``.file: str``) and
``default_variant: dict[str, str]`` works.
"""

from __future__ import annotations

import logging
import platform
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EMERGENCY_FALLBACK_CHAIN = ("quantized", "int8", "fp16", "fp32")


def detect_platform_key() -> str:
    """Return a stable key used to look up ``default_variant`` in registry YAML.

    Format: f"{sys.platform}_{platform.machine().lower()}"
    Examples: 'darwin_arm64', 'win32_amd64', 'linux_x86_64'.
    """
    return f"{sys.platform}_{platform.machine().lower()}"


def _find_onnx_model(model_dir: Path) -> Path | None:
    """Find the best ONNX model file, checking root and onnx/ subdirectory.

    Legacy scan: model_quantized.onnx > model_int8.onnx > model.onnx > first *.onnx.
    Used as a fallback for models without a ``variants`` block in their YAML.
    """
    for base in [model_dir, model_dir / "onnx"]:
        if not base.is_dir():
            continue
        for name in ["model_quantized.onnx", "model_int8.onnx", "model.onnx"]:
            candidate = base / name
            if candidate.exists():
                return candidate
        fallback = sorted(base.glob("*.onnx"))
        if fallback:
            return fallback[0]
    return None


def resolve_variant_name(
    meta: Any,
    *,
    override: str | None = None,
    platform_key: str | None = None,
) -> str | None:
    """Pick a variant name from a model's ``variants`` block.

    Priority:
      1. ``override`` if set AND present in ``meta.variants``.
      2. ``meta.default_variant[platform_key]`` if valid.
      3. ``meta.default_variant['_fallback']`` if valid.
      4. First entry in ``_EMERGENCY_FALLBACK_CHAIN`` that exists in
         ``meta.variants``.
      5. Last resort: first variant in iteration order.

    Returns ``None`` if ``meta`` is ``None`` or has no ``variants`` — the
    caller should fall back to a legacy scan (``_find_onnx_model``).
    """
    if meta is None or not getattr(meta, "variants", None):
        return None

    if override:
        if override in meta.variants:
            return override
        logger.warning(
            "Variant override %r not in model %r variants %s; using platform default",
            override,
            getattr(meta, "id", "?"),
            sorted(meta.variants.keys()),
        )

    key = platform_key or detect_platform_key()
    candidate = meta.default_variant.get(key) or meta.default_variant.get("_fallback")
    if candidate and candidate in meta.variants:
        return candidate

    for name in _EMERGENCY_FALLBACK_CHAIN:
        if name in meta.variants:
            return name

    return next(iter(meta.variants))


def resolve_variant_path(
    model_dir: Path,
    meta: Any,
    *,
    override: str | None = None,
    platform_key: str | None = None,
) -> Path | None:
    """Resolve which .onnx file in ``model_dir`` should be loaded.

    For managed models with a ``variants`` block, returns the file the
    resolver picked (or ``None`` if that file isn't present on disk —
    caller should trigger a download). For models without ``variants``
    (legacy YAML or user-supplied dirs), falls back to scan-based
    priority via :func:`_find_onnx_model`.
    """
    if meta is None or not getattr(meta, "variants", None):
        return _find_onnx_model(model_dir)

    name = resolve_variant_name(meta, override=override, platform_key=platform_key)
    if name is None:
        return _find_onnx_model(model_dir)

    variant = meta.variants[name]
    candidate = model_dir / variant.file
    if candidate.exists():
        return candidate
    bare = model_dir / Path(variant.file).name
    if bare.exists():
        return bare
    return None


__all__ = [
    "detect_platform_key",
    "resolve_variant_name",
    "resolve_variant_path",
    "_find_onnx_model",
]
