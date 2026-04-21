"""Runtime directory management for durable and operational local storage."""
import logging
from pathlib import Path
from typing import Optional

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
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure all necessary directories exist."""
        directories = [
            self.base_dir,
            self.personalities_dir,
            self.data_dir,
            self.app_data_dir,
            self.memory_dir,
            self.chat_dir,
            self.resources_dir,
            self.chat_resources_dir,
            self.runtime_dir,
            self.cache_dir,
            self.models_cache_dir,
            self.reranker_models_dir,
            self.embedding_models_dir,
            self.plugins_cache_dir,
            self.others_dir,
            self.logs_dir,
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

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
    def cache_dir(self) -> Path:
        """Rebuildable runtime and plugin cache directory."""
        return self.base_dir / "cache"

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
    def persona_registry_db_path(self) -> Path:
        """Persona registry database path."""
        return self.app_data_dir / "persona_registry.db"

    @property
    def behavior_db_path(self) -> Path:
        """Behavior evolution database path."""
        return self.memory_dir / "behavior_evolution.db"

    @property
    def scenario_prompts_db_path(self) -> Path:
        """Scenario prompts database path."""
        return self.app_data_dir / "scenario_prompts.db"

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
    def sensor_state_db_path(self) -> Path:
        """Sensor runtime state database path."""
        return self.runtime_dir / "sensor_state.db"

    @property
    def background_tasks_db_path(self) -> Path:
        """Background-task persistence database path."""
        return self.runtime_dir / "background_tasks.db"

    @property
    def task_orchestrations_path(self) -> Path:
        """Task-orchestration recovery store path."""
        return self.runtime_dir / "task_orchestrations.json"

    def plugin_cache_dir(self, plugin_id: str) -> Path:
        """Return the cache directory for one plugin."""
        normalized = str(plugin_id or "").strip().replace("/", "_").replace("\\", "_")
        if not normalized:
            raise ValueError("plugin_id is required")
        return self.plugins_cache_dir / normalized

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

    def get_personality_path(self, name: str = "default") -> str:
        """
        Get personality configuration file path (string format, for compatibility).

        Args:
            name: Personality name.

        Returns:
            Personality directory path string.
        """
        return str(self.personalities_dir)

    def initialize_default_personality(self) -> None:
        """Ensure the personalities directory exists.

        The active persona is tracked in the persona registry (SQLite),
        not via a ``current`` text file.  JSON preset files may still
        be placed in ``personalities_dir`` for seeding / migration.
        """
        self.personalities_dir.mkdir(parents=True, exist_ok=True)

    @property
    def current_personality_file(self) -> Path:
        """Legacy helper — returns the path but the file is no longer written."""
        return self.personalities_dir / "current"


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
