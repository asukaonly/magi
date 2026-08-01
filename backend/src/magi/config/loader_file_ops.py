"""File loading and default-materialization helpers for ConfigLoader."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

from .diff_utils import deep_merge_dict
from .llm_registry import LLMProviderRegistryModel, build_runtime_llm_defaults, load_llm_provider_registry
from .models import AppConfig

logger = logging.getLogger(__name__)


def _loader_facade() -> Any:
    from . import loader

    return loader


class ConfigLoaderFileOpsMixin:
    """Load YAML files, materialize defaults, and build AppConfig."""

    _config_file: Path
    _llm_config_file: Path
    _lifecycle_config_file: Path
    _lifecycle_example_config_file: Path
    _llm_provider_registry_file: Path
    _plugins_index_file: Path
    _yaml_data: Dict[str, Any]

    def _snapshot_config_signature(self) -> Tuple[Tuple[str, int, int], ...]:
        """Capture a lightweight signature of split config files for cache invalidation."""
        facade = _loader_facade()
        tracked_paths = [
            self._config_file,
            self._llm_config_file,
            self._lifecycle_config_file,
            self._plugins_index_file,
            *sorted(facade.get_plugins_config_dir().glob("*.yaml")),
        ]
        signature: list[tuple[str, int, int]] = []
        seen_paths: set[str] = set()

        for path in tracked_paths:
            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            if path.exists():
                stat = path.stat()
                signature.append((key, stat.st_mtime_ns, stat.st_size))
            else:
                signature.append((key, -1, -1))

        return tuple(signature)

    def _ensure_config_exists(self):
        """Create config directory and copy example config if needed."""
        facade = _loader_facade()
        config_dir = facade.get_config_dir()
        config_file = facade.get_config_file()
        plugins_dir = facade.get_plugins_config_dir()
        example_file = facade.get_example_config_file()

        if not config_dir.exists():
            config_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created config directory: {config_dir}")

        if not plugins_dir.exists():
            plugins_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created plugin config directory: {plugins_dir}")

        if not self._llm_provider_registry_file.exists():
            raise FileNotFoundError(f"Missing packaged LLM provider registry file: {self._llm_provider_registry_file}")

        if not config_file.exists():
            if example_file.exists():
                shutil.copy(example_file, config_file)
                logger.info(f"Copied example config to {config_file}")
            else:
                self._create_default_config_file(config_file)
                logger.info(f"Created default config at {config_file}")

        if not self._llm_config_file.exists():
            self._write_yaml_file(self._llm_config_file, {})
            logger.info(f"Created llm config file: {self._llm_config_file}")

        if not self._lifecycle_config_file.exists():
            lifecycle_defaults = self._load_yaml_file(self._lifecycle_example_config_file)
            self._write_yaml_file(self._lifecycle_config_file, lifecycle_defaults)
            logger.info(f"Created lifecycle config file: {self._lifecycle_config_file}")

        data_dir = facade.get_data_dir()
        if not data_dir.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created data directory: {data_dir}")

        self._ensure_split_plugin_config_layout()

    def _create_default_config_file(self, config_file: Path):
        """Create a minimal default config file."""
        default_config = {
            "agent": {
                "name": "magi-agent",
                "num_task_agents": 2,
            },
            "features": {
                "enable_three_layer_arch": False,
                "enable_skills": True,
            },
            "tools": {
                "weather": {"enabled": True, "api_key": ""},
                "web_search": {"enabled": True, "api_key": ""},
            },
            "plugins": {
                "scan_paths": ["plugins", "~/.magi/plugins"],
            },
            "debug": False,
            "log_level": "INFO",
        }

        self._write_yaml_file(config_file, default_config)

    def _plugins_config_dir(self) -> Path:
        return _loader_facade().get_plugins_config_dir()

    def _plugin_settings_file(self, plugin_id: str) -> Path:
        return _loader_facade().get_plugin_settings_file(plugin_id)

    def _load_yaml_file(self, path: Path) -> Dict[str, Any]:
        """Load and parse a YAML file, returning an empty dict on failure."""
        if not path.exists():
            return {}

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Failed to load config file {path}: {e}")
            return {}

    def _write_yaml_file(self, path: Path, data: Dict[str, Any]) -> None:
        """Write a YAML file with a normalized dict payload.

        Uses ``safe_dump`` (not ``dump``) so non-native types (Python
        enums, dataclasses, custom objects) refuse to serialize. This
        prevents the silent-corruption mode where ``yaml.dump`` emits
        an unsafe ``!!python/object/apply:Foo.Bar`` tag that the
        symmetric ``yaml.safe_load`` then refuses to read, leaving the
        settings UI showing an empty config and a stack trace in the
        backend logs. Callers must convert enums to their ``.value``
        (or use ``pydantic.BaseModel.model_dump(mode="json")``) BEFORE
        passing data here — ``safe_dump`` will raise loudly otherwise.

        The write is atomic and serialize-first: the payload is fully
        rendered to a string before the destination is touched, then
        staged in a sibling temp file and ``os.replace``-d into place.
        So a ``safe_dump`` failure (the "raise loudly" case above) or a
        crash mid-write can never leave a truncated or empty config
        behind — the previous file survives intact.
        """
        text = yaml.safe_dump(
            data, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Path | None = None
        tmp_fd: int | None = None
        try:
            tmp_fd, tmp_name = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                tmp_fd = None
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_fd is not None:
                os.close(tmp_fd)
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _load_yaml(self) -> Dict[str, Any]:
        """Load and parse YAML configuration file."""
        data = self._load_yaml_file(self._config_file)
        data = self._merge_split_plugin_config(data)
        data["llm"] = self._load_effective_llm_config()
        lifecycle_data = self._load_yaml_file(self._lifecycle_config_file)
        if isinstance(lifecycle_data.get("lifecycle"), dict):
            data["lifecycle"] = lifecycle_data["lifecycle"]
        else:
            data["lifecycle"] = lifecycle_data
        return data

    def _load_effective_llm_config(self) -> Dict[str, Any]:
        """Load effective LLM config by merging registry defaults and runtime overrides."""
        defaults = self._build_llm_defaults()
        overrides = self._load_yaml_file(self._llm_config_file)
        return deep_merge_dict(defaults, overrides)

    def _load_llm_provider_registry(self) -> LLMProviderRegistryModel:
        """Load packaged provider registry for LLM default generation."""
        return load_llm_provider_registry(
            self._llm_provider_registry_file,
            fallback=LLMProviderRegistryModel(),
        )

    def _build_llm_defaults(self) -> Dict[str, Any]:
        """Build default LLM config from provider registry."""
        return build_runtime_llm_defaults(self._load_llm_provider_registry())

    def _build_config(self) -> AppConfig:
        """Build final config by merging YAML + model defaults."""
        return AppConfig.model_validate(self._yaml_data)

    def _set_nested_yaml(self, data: Dict, path: str, value: Any):
        """Set nested value in YAML data structure."""
        parts = path.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    def _prune_deprecated_memory_settings(self, data: Dict[str, Any]) -> None:
        """Remove no-longer-supported memory vector config overrides from runtime YAML."""
        agent = data.get("agent")
        if not isinstance(agent, dict):
            return
        memory = agent.get("memory")
        if not isinstance(memory, dict):
            return

        memory.pop("async_embeddings", None)
        embedding = memory.get("embedding")
        if isinstance(embedding, dict):
            embedding.pop("backend", None)
            if not embedding:
                memory.pop("embedding", None)


__all__ = ["ConfigLoaderFileOpsMixin"]
