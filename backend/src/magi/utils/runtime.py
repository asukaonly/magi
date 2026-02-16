"""
Runtime data directory management

Put all runtime-generated data in ~/.magi directory, separate from code
"""
import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Runtimepaths:
    """Runtime path management"""

    def __init__(self, base_dir: Optional[path] = None):
        """
        initialize runtime paths

        Args:
            base_dir: Base directory, defaults to ~/.magi
        """
        if base_dir is None:
            # Use .magi folder under user home directory
            home = path.home()
            base_dir = home / ".magi"

        self.base_dir = path(base_dir)
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure all necessary directories exist"""
        directories = [
            self.base_dir,
            self.personalities_dir,
            self.data_dir,
            self.memories_dir,
            self.others_dir,  # Others' memory directory
            self.logs_dir,
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

        logger.info(f"Runtime directory: {self.base_dir}")

    @property
    def personalities_dir(self) -> path:
        """Personality configuration directory"""
        return self.base_dir / "personalities"

    @property
    def data_dir(self) -> path:
        """data directory"""
        return self.base_dir / "data"

    @property
    def memories_dir(self) -> path:
        """Memory database directory"""
        return self.data_dir / "memories"

    @property
    def others_dir(self) -> path:
        """Others' memory directory (MD file storage)"""
        return self.base_dir / "others"

    @property
    def logs_dir(self) -> path:
        """Log directory"""
        return self.base_dir / "logs"

    @property
    def behavior_db_path(self) -> path:
        """Behavior evolution database path"""
        return self.memories_dir / "behavior_evolution.db"

    @property
    def emotional_db_path(self) -> path:
        """Emotional state database path"""
        return self.memories_dir / "emotional_state.db"

    @property
    def growth_db_path(self) -> path:
        """Growth memory database path"""
        return self.memories_dir / "growth_memory.db"

    @property
    def self_memory_db_path(self) -> path:
        """Self memory database path (compatible)"""
        return self.memories_dir / "self_memory_v2.db"

    @property
    def events_db_path(self) -> path:
        """event database path"""
        return self.data_dir / "events.db"

    def other_file(self, user_id: str) -> path:
        """
        Get others' memory file path

        Args:
            user_id: User id

        Returns:
            Others' memory MD file path
        """
        # Convert user id to safe filename (replace special characters)
        safe_name = user_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.others_dir / f"{safe_name}.md"

    def personality_file(self, name: str) -> path:
        """
        Get personality configuration file path

        Args:
            name: Personality name (without extension)

        Returns:
            Full path to personality configuration file
        """
        return self.personalities_dir / f"{name}.md"

    def get_personality_path(self, name: str = "default") -> str:
        """
        Get personality configuration file path (string format, for compatibility)

        Args:
            name: Personality name

        Returns:
            Personality directory path string
        """
        return str(self.personalities_dir)

    def initialize_default_personality(self):
        """
        initialize default personality configuration

        If there's nottt default.md in runtime directory, copy one from code directory
        Also ensure current file exists (records currently used personality)
        """
        # Copy default.md template (if it doesn't exist)
        default_file = self.personality_file("default")

        if not default_file.exists():
            # Try to copy from code directory
            possible_sources = [
                path("./personalities/default.md"),
                path("./backend/personalities/default.md"),
                path(__file__).parent.parent.parent.parent / "personalities" / "default.md",
            ]

            for source in possible_sources:
                if source.exists():
                    import shutil
                    shutil.copy(source, default_file)
                    logger.info(f"Copied default personality from {source} to {default_file}")
                    break
            else:
                logger.warning(f"Could not find default personality to copy to {default_file}")
        else:
            logger.info(f"Default personality exists: {default_file}")

        # Ensure current file exists
        current_file = self.personalities_dir / "current"
        if not current_file.exists():
            # Try to select a personality from existing .md files as default
            md_files = list(self.personalities_dir.glob("*.md"))
            valid_personalities = [f.stem for f in md_files if f.stem != "default"]

            if valid_personalities:
                # Use first personality as default
                current_file.write_text(valid_personalities[0])
                logger.info(f"Created current file with personality: {valid_personalities[0]}")
            else:
                # If nottt custom personality, use default
                current_file.write_text("default")
                logger.info("Created current file with default personality")
        else:
            current_name = current_file.read_text().strip()
            logger.info(f"Current personality: {current_name}")

    @property
    def current_personality_file(self) -> path:
        """Get current personality file path"""
        current_file = self.personalities_dir / "current"
        if current_file.exists():
            name = current_file.read_text().strip()
        else:
            name = "default"
        return self.personality_file(name)


# Global instance
_runtime_paths: Optional[Runtimepaths] = None


def get_runtime_paths() -> Runtimepaths:
    """Get global runtime paths instance"""
    global _runtime_paths
    if _runtime_paths is None:
        _runtime_paths = Runtimepaths()
    return _runtime_paths


def set_runtime_dir(path: str | path):
    """
    Set custom runtime directory

    Args:
        path: Custom directory path
    """
    global _runtime_paths
    _runtime_paths = Runtimepaths(path(path))


def init_runtime_data():
    """
    initialize runtime data

    Call at application startup to ensure default configuration exists
    """
    paths = get_runtime_paths()
    paths.initialize_default_personality()
