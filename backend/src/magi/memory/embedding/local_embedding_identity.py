"""Identity helpers for local embedding model files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config.local_embedding_registry import get_local_embedding_registry
from ...utils.runtime import RuntimePaths, get_runtime_paths
from .local_embedding_resolution import resolve_variant_path

LOCAL_EMBEDDING_RUNTIME_FAMILY = "onnxruntime"
_SIDE_CAR_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "sentencepiece.bpe.model",
)


@dataclass(frozen=True, slots=True)
class LocalEmbeddingFingerprint:
    """Stable local embedding model identity derived from model files."""

    model_dir: Path
    model_name: str
    model_file_hash: str
    dimension: int | None
    runtime_family: str = LOCAL_EMBEDDING_RUNTIME_FAMILY

    @property
    def identity_key(self) -> str:
        return f"local:{self.runtime_family}:{self.model_file_hash}"


def compute_local_embedding_model_fingerprint(
    local_config: Any,
    *,
    runtime_paths: RuntimePaths | None = None,
) -> LocalEmbeddingFingerprint | None:
    """Return a content hash for the configured local embedding model."""

    paths = runtime_paths or get_runtime_paths()
    model_dir = resolve_local_embedding_model_dir(local_config, runtime_paths=paths)
    if model_dir is None or not model_dir.exists():
        return None

    source = _enum_value(getattr(local_config, "model_source", "managed"))
    meta = None
    if source == "managed":
        model_id = str(getattr(local_config, "managed_model_id", "") or "").strip()
        if model_id:
            meta = get_local_embedding_registry().get(model_id)
    variant_override = getattr(local_config, "variant", None)
    model_path = resolve_variant_path(model_dir, meta, override=variant_override)
    if model_path is None:
        return None

    model_name = _resolve_local_embedding_model_name(local_config, model_dir)
    dimension = resolve_local_embedding_dimension(local_config, model_dir)
    digest = _hash_model_files(model_dir=model_dir, model_path=model_path)
    return LocalEmbeddingFingerprint(
        model_dir=model_dir,
        model_name=model_name,
        model_file_hash=digest,
        dimension=dimension,
    )


def resolve_local_embedding_model_dir(
    local_config: Any,
    *,
    runtime_paths: RuntimePaths | None = None,
) -> Path | None:
    """Resolve the local embedding model directory from a config object."""

    source = _enum_value(getattr(local_config, "model_source", "managed"))
    if source == "external":
        path_value = str(getattr(local_config, "model_dir_path", "") or "").strip()
        return Path(path_value).expanduser() if path_value else None

    model_id = str(getattr(local_config, "managed_model_id", "") or "").strip()
    if not model_id:
        return None
    paths = runtime_paths or get_runtime_paths()
    return Path(paths.managed_embedding_model_dir(model_id))


def resolve_local_embedding_dimension(local_config: Any, model_dir: Path) -> int | None:
    """Resolve the configured local embedding dimension without loading ONNX."""

    source = _enum_value(getattr(local_config, "model_source", "managed"))
    if source == "managed":
        model_id = str(getattr(local_config, "managed_model_id", "") or "").strip()
        meta = get_local_embedding_registry().get(model_id) if model_id else None
        if meta is not None:
            return int(meta.dimension)

    config_path = model_dir / "config.json"
    if not config_path.exists():
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw_dimension = payload.get("hidden_size") or payload.get("dim") or payload.get("embedding_dim")
    try:
        return int(raw_dimension) if raw_dimension is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_local_embedding_model_name(local_config: Any, model_dir: Path) -> str:
    source = _enum_value(getattr(local_config, "model_source", "managed"))
    if source == "managed":
        model_id = str(getattr(local_config, "managed_model_id", "") or "").strip()
        if model_id:
            return model_id
    return model_dir.name or "local"


def _hash_model_files(*, model_dir: Path, model_path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"runtime:{LOCAL_EMBEDDING_RUNTIME_FAMILY}\n".encode("utf-8"))

    paths: list[Path] = [model_path]
    for relative_name in _SIDE_CAR_FILES:
        candidate = model_dir / relative_name
        if candidate.exists() and candidate.is_file():
            paths.append(candidate)

    for path in sorted(set(paths), key=lambda item: item.relative_to(model_dir).as_posix()):
        relative = path.relative_to(model_dir).as_posix()
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        hasher.update(b"\0")
    return hasher.hexdigest()


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


__all__ = [
    "LOCAL_EMBEDDING_RUNTIME_FAMILY",
    "LocalEmbeddingFingerprint",
    "compute_local_embedding_model_fingerprint",
    "resolve_local_embedding_dimension",
    "resolve_local_embedding_model_dir",
]
