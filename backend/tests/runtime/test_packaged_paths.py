from __future__ import annotations

from pathlib import Path

from magi.config.cross_encoder_registry import _default_registry_path as cross_encoder_registry_path
from magi.config.loader import get_example_config_file, get_llm_provider_registry_file
from magi.config.local_embedding_registry import _default_registry_path as local_embedding_registry_path
from magi.utils import packaged_paths


def test_packaged_paths_use_meipass_when_frozen(monkeypatch) -> None:
    frozen_root = Path("/tmp/magi-meipass")
    resolved_frozen_root = frozen_root.resolve()

    monkeypatch.setattr(packaged_paths.sys, "_MEIPASS", str(frozen_root), raising=False)
    packaged_paths.get_repo_root.cache_clear()
    packaged_paths.get_backend_root.cache_clear()
    local_embedding_registry_path.cache_clear()
    cross_encoder_registry_path.cache_clear()

    assert packaged_paths.get_repo_root() == resolved_frozen_root
    assert packaged_paths.get_backend_root() == resolved_frozen_root
    assert get_llm_provider_registry_file() == resolved_frozen_root / "configs" / "llm_providers.yaml"
    assert get_example_config_file() == resolved_frozen_root / "configs" / "config.example.yaml"
    assert local_embedding_registry_path() == resolved_frozen_root / "configs" / "local_embedding_models.yaml"
    assert cross_encoder_registry_path() == resolved_frozen_root / "configs" / "cross_encoder_models.yaml"
