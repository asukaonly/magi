"""Runtime directory management for durable and operational local storage."""

import logging
import os
from pathlib import Path
from typing import Optional

from .private_data import protect_private_data_tree

# Use standard logging to avoid circular imports
logger = logging.getLogger(__name__)


class RuntimePaths:
    """Runtime path management."""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        initialize runtime paths

        Args:
            base_dir: Base directory, defaults to ~/.magi
        """
        if base_dir is None:
            # Use .magi folder under user home directory.
            home = Path.home()
            base_dir = home / ".magi"

        self.base_dir = Path(base_dir)
        protect_private_data_tree(self.base_dir)
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure all necessary directories exist."""
        directories = [
            self.base_dir,
            self.personalities_dir,
            self.data_dir,
            self.app_data_dir,
            self.memory_dir,
            self.memory_backups_dir,
            self.chat_dir,
            self.resources_dir,
            self.chat_resources_dir,
            self.runtime_dir,
            self.memory_portability_dir,
            self.cache_dir,
            self.workspaces_dir,
            self.models_cache_dir,
            self.reranker_models_dir,
            self.embedding_models_dir,
            self.plugins_cache_dir,
            self.others_dir,
            self.logs_dir,
            self.config_dir,
            self.mcp_config_dir,
        ]

        for directory in directories:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                directory.chmod(0o700)

        logger.info(f"Runtime directory: {self.base_dir}")

    @property
    def personalities_dir(self) -> Path:
        """Personality configuration directory."""
        return self.base_dir / "personalities"

    @property
    def data_dir(self) -> Path:
        """Durable product data directory."""
        return self.base_dir / "data"

    @property
    def app_data_dir(self) -> Path:
        """Durable app-owned data that is not chat truth or memory."""
        return self.data_dir / "app"

    @property
    def memory_dir(self) -> Path:
        """Canonical memory storage directory."""
        return self.data_dir / "memory"

    @property
    def memory_backups_dir(self) -> Path:
        """Private default destination for automatic memory safety backups."""
        return self.memory_dir / "backups"

    @property
    def manual_entry_assets_dir(self) -> Path:
        """Magi-managed assets referenced by manual memory entries."""
        return self.data_dir / "media" / "manual_entries"

    @property
    def chat_dir(self) -> Path:
        """Durable chat-domain storage directory."""
        return self.data_dir / "chat"

    @property
    def resources_dir(self) -> Path:
        """Managed durable resource directory."""
        return self.data_dir / "resources"

    @property
    def chat_resources_dir(self) -> Path:
        """Managed chat attachment asset directory."""
        return self.resources_dir / "chat"

    @property
    def chat_images_dir(self) -> Path:
        """Managed chat image attachment directory."""
        return self.chat_resources_dir / "images"

    @property
    def chat_files_dir(self) -> Path:
        """Managed chat file attachment directory."""
        return self.chat_resources_dir / "files"

    @property
    def chat_derived_dir(self) -> Path:
        """Managed chat derived-asset directory."""
        return self.chat_resources_dir / "derived"

    @property
    def runtime_dir(self) -> Path:
        """Runtime coordination and observability directory."""
        return self.base_dir / "runtime"

    @property
    def memory_portability_dir(self) -> Path:
        """Private staging and recovery state for memory portability work."""
        return self.runtime_dir / "memory-portability"

    @property
    def cache_dir(self) -> Path:
        """Rebuildable runtime and plugin cache directory."""
        return self.base_dir / "cache"

    @property
    def workspaces_dir(self) -> Path:
        """Private workspace-scoped runtime buckets."""
        return self.base_dir / "workspaces"

    @property
    def plugins_cache_dir(self) -> Path:
        """Plugin-owned cache directory."""
        return self.cache_dir / "plugins"

    @property
    def models_cache_dir(self) -> Path:
        """Managed local model cache directory."""
        return self.cache_dir / "models"

    @property
    def reranker_models_dir(self) -> Path:
        """Managed local reranker model cache directory."""
        return self.models_cache_dir / "rerank"

    @property
    def embedding_models_dir(self) -> Path:
        """Managed local embedding model cache directory."""
        return self.models_cache_dir / "embed"

    @property
    def others_dir(self) -> Path:
        """Others' memory directory (MD file storage)."""
        return self.base_dir / "others"

    @property
    def logs_dir(self) -> Path:
        """Log directory."""
        return self.base_dir / "logs"

    @property
    def config_dir(self) -> Path:
        """User-editable runtime configuration directory."""
        return self.base_dir / "config"

    @property
    def mcp_config_dir(self) -> Path:
        """Per-server MCP client configuration directory."""
        return self.config_dir / "mcp"

    @property
    def persona_registry_db_path(self) -> Path:
        """Persona registry database path."""
        return self.app_data_dir / "persona_registry.db"

    @property
    def behavior_db_path(self) -> Path:
        """Behavior evolution database path."""
        return self.memory_dir / "behavior_evolution.db"

    @property
    def emotional_db_path(self) -> Path:
        """Emotional state database path."""
        return self.memory_dir / "emotional_state.db"

    @property
    def growth_db_path(self) -> Path:
        """Growth memory database path."""
        return self.memory_dir / "growth_memory.db"

    @property
    def self_memory_db_path(self) -> Path:
        """Self memory database path."""
        return self.memory_dir / "self_memory_v2.db"

    @property
    def memory_db_path(self) -> Path:
        """Shared memory database path for L0/L2/L3/L4."""
        return self.memory_dir / "memory.db"

    @property
    def message_queue_db_path(self) -> Path:
        """Message bus queue database path."""
        return self.runtime_dir / "message_queue.db"

    @property
    def chat_db_path(self) -> Path:
        """Dedicated chat-domain database path."""
        return self.chat_dir / "chat.db"

    @property
    def l1_memory_db_path(self) -> Path:
        """L1 memory database path."""
        return self.memory_dir / "l1_events.db"

    @property
    def runtime_trace_db_path(self) -> Path:
        """Runtime trace database path."""
        return self.runtime_dir / "runtime_trace.db"

    @property
    def llm_usage_db_path(self) -> Path:
        """LLM usage statistics database path."""
        return self.runtime_dir / "llm_usage.db"

    @property
    def scheduler_db_path(self) -> Path:
        """Unified scheduler database path."""
        return self.runtime_dir / "scheduler.db"

    @property
    def initialization_state_db_path(self) -> Path:
        """Versioned startup-step state database path."""
        return self.runtime_dir / "bootstrap_state.db"

    @property
    def sensor_state_db_path(self) -> Path:
        """Sensor runtime state database path."""
        return self.runtime_dir / "sensor_state.db"

    @property
    def background_tasks_db_path(self) -> Path:
        """Background-task persistence database path."""
        return self.runtime_dir / "background_tasks.db"

    @property
    def permission_rules_db_path(self) -> Path:
        """Permission rules database path."""
        return self.runtime_dir / "permission_rules.db"

    @property
    def channels_db_path(self) -> Path:
        """Channel session mapping database path."""
        return self.data_dir / "channels" / "channels.db"

    @property
    def identity_db_path(self) -> Path:
        """Identity layer database path.

        Stores ``user_identity_bindings`` rows mapping
        ``(channel_type, external_user_id)`` to a canonical
        ``MagiUserID``. Independent file (not co-located with
        channels.db) because identity is cross-cutting — see
        ``docs/identity-architecture.md``.
        """
        return self.data_dir / "identity" / "identity.db"

    @property
    def batch_db_path(self) -> Path:
        """Batch orchestrator manifest database path."""
        return self.data_dir / "batch" / "batch.db"

    def plugin_cache_dir(self, plugin_id: str) -> Path:
        """Return the cache directory for one plugin."""
        normalized = str(plugin_id or "").strip().replace("/", "_").replace("\\", "_")
        if not normalized:
            raise ValueError("plugin_id is required")
        return self.plugins_cache_dir / normalized

    def workspace_bucket_dir(self, workspace_id: str) -> Path:
        """Return the private global bucket for one workspace."""
        normalized = (
            str(workspace_id or "")
            .strip()
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
        )
        if not normalized:
            raise ValueError("workspace_id is required")
        return self.workspaces_dir / normalized

    def managed_reranker_model_dir(self, model_id: str) -> Path:
        """Return the managed cache directory for one reranker model."""
        normalized = str(model_id or "").strip().replace("/", "_").replace("\\", "_")
        if not normalized:
            raise ValueError("model_id is required")
        return self.reranker_models_dir / normalized

    def managed_embedding_model_dir(self, model_id: str) -> Path:
        """Return the managed cache directory for one embedding model."""
        normalized = str(model_id or "").strip().replace("/", "_").replace("\\", "_")
        if not normalized:
            raise ValueError("model_id is required")
        return self.embedding_models_dir / normalized

    def other_file(self, user_id: str) -> Path:
        """
        Get others' memory file path.

        Args:
            user_id: User ID.

        Returns:
            Path to the others' memory MD file.
        """
        # Convert user id to safe filename (replace special characters)
        safe_name = user_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.others_dir / f"{safe_name}.md"

    def personality_file(self, name: str) -> Path:
        """
        Get personality configuration file path.

        Args:
            name: Personality name (without extension).

        Returns:
            Full path to personality configuration file.
        """
        return self.personalities_dir / f"{name}.json"

    def initialize_default_personality(self) -> None:
        """Ensure the personalities directory exists.

        The active persona is tracked in the persona registry (SQLite),
        not via a ``current`` text file.  JSON preset files may still
        be placed in ``personalities_dir`` for seeding / migration.
        """
        self.personalities_dir.mkdir(parents=True, exist_ok=True)



DEFAULT_CHAT_WORKSPACE_DIRNAME = "chat-workspace"


def get_default_chat_workspace_path() -> str:
    """Return the managed default workspace path for desktop chat sessions."""
    workspace_path = (Path.home() / ".magi" / DEFAULT_CHAT_WORKSPACE_DIRNAME).expanduser()
    workspace_path.mkdir(parents=True, exist_ok=True)
    return str(workspace_path.resolve())


# Global instance
_runtime_paths: Optional[RuntimePaths] = None


def get_runtime_paths() -> RuntimePaths:
    """Get global runtime paths instance."""
    global _runtime_paths
    if _runtime_paths is None:
        _runtime_paths = RuntimePaths()
    return _runtime_paths


def set_runtime_dir(path: str | Path):
    """
    Set custom runtime directory.

    Args:
        path: Custom directory path.
    """
    global _runtime_paths
    _runtime_paths = RuntimePaths(Path(path))


def init_runtime_data():
    """
    Initialize runtime data.

    Call at application startup to ensure default configuration exists.
    """
    paths = get_runtime_paths()
    paths.initialize_default_personality()
