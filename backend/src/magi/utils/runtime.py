"""
Runtime data directory management.

Put all runtime-generated data in ~/.magi directory, separate from code.
"""
import json
import logging
from pathlib import Path
from typing import Optional

# Use standard logging to avoid circular imports
logger = logging.getLogger(__name__)


class Runtimepaths:
    """Runtime path management"""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        initialize runtime paths

        Args:
            base_dir: Base directory, defaults to ~/.magi
        """
        if base_dir is None:
            # Use .magi folder under user home directory
            home = Path.home()
            base_dir = home / ".magi"

        self.base_dir = Path(base_dir)
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
    def personalities_dir(self) -> Path:
        """Personality configuration directory"""
        return self.base_dir / "personalities"

    @property
    def data_dir(self) -> Path:
        """data directory"""
        return self.base_dir / "data"

    @property
    def memories_dir(self) -> Path:
        """Memory database directory"""
        return self.data_dir / "memories"

    @property
    def others_dir(self) -> Path:
        """Others' memory directory (MD file storage)"""
        return self.base_dir / "others"

    @property
    def logs_dir(self) -> Path:
        """Log directory"""
        return self.base_dir / "logs"

    @property
    def behavior_db_path(self) -> Path:
        """Behavior evolution database path"""
        return self.memories_dir / "behavior_evolution.db"

    @property
    def scenario_prompts_db_path(self) -> Path:
        """Scenario prompts database path"""
        return self.memories_dir / "scenario_prompts.db"

    @property
    def emotional_db_path(self) -> Path:
        """Emotional state database path"""
        return self.memories_dir / "emotional_state.db"

    @property
    def growth_db_path(self) -> Path:
        """Growth memory database path"""
        return self.memories_dir / "growth_memory.db"

    @property
    def self_memory_db_path(self) -> Path:
        """Self memory database path (compatible)"""
        return self.memories_dir / "self_memory_v2.db"

    @property
    def events_db_path(self) -> Path:
        """event database path"""
        return self.data_dir / "events.db"

    def other_file(self, user_id: str) -> Path:
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

    def personality_file(self, name: str) -> Path:
        """
        Get personality configuration file path

        Args:
            name: Personality name (without extension)

        Returns:
            Full path to personality configuration file
        """
        return self.personalities_dir / f"{name}.json"

    @staticmethod
    def _default_personality_payload() -> dict:
        """Default personality payload for runtime bootstrap."""
        return {
            "persona_entity": {
                "basic_profile": {
                    "name": "AI Assistant",
                    "age": "Unknown",
                    "gender": "Unknown",
                    "occupation": "Assistant",
                    "core_background": "",
                },
                "psychological_traits": {
                    "communication_tone": "Calm and supportive",
                    "confidence_level": "Medium",
                    "empathy_threshold": "Shows care when user is stressed",
                    "high_frequency_keywords": [],
                },
                "social_responses": {
                    "praise_reaction": "",
                    "criticism_reaction": "",
                    "obedience_strategy": "",
                },
                "behavioral_strategies": {
                    "error_handling": "",
                    "refusal_style": "",
                },
            },
            "cached_phrases": {
                "on_init": ["Hi, I'm online.", "Ready when you are."],
                "on_wake": ["Back again?", "I'm here."],
                "on_error_generic": ["That failed. Let me retry.", "Oops, tool hiccup."],
                "on_success": ["Done.", "Handled."],
                "on_switch_attempt": ["Stay with me, I know your style.", "Give me one more chance."],
            },
            "appearance_prompt": "",
            "state_transition_protocol": [],
        }

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
        Initialize personality configuration.

        Only creates default.json as fallback when:
        - current file doesn't exist, or
        - current points to a non-existent personality
        """
        current_file = self.personalities_dir / "current"
        needs_fallback = False

        if current_file.exists():
            current_name = current_file.read_text().strip()
            personality_file = self.personality_file(current_name)

            if personality_file.exists():
                logger.info(f"Current personality: {current_name}")
            else:
                # Current points to non-existent personality
                logger.warning(f"Current personality '{current_name}' not found, creating fallback")
                needs_fallback = True
        else:
            # No current file
            logger.info("No current personality file found")
            needs_fallback = True

        if needs_fallback:
            # Create default.json as fallback
            default_file = self.personality_file("default")
            if not default_file.exists():
                default_file.write_text(
                    json.dumps(self._default_personality_payload(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"Created default personality JSON: {default_file}")

            # Point current to default
            current_file.write_text("default")
            logger.info("Set current personality to default")

    @property
    def current_personality_file(self) -> Path:
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


def set_runtime_dir(path: str | Path):
    """
    Set custom runtime directory

    Args:
        path: Custom directory path
    """
    global _runtime_paths
    _runtime_paths = Runtimepaths(Path(path))


def init_runtime_data():
    """
    initialize runtime data

    Call at application startup to ensure default configuration exists
    """
    paths = get_runtime_paths()
    paths.initialize_default_personality()
