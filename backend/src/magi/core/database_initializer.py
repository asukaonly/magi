"""Database initializer for runtime-owned SQLite stores."""
import logging
from typing import List, Callable, Awaitable

from .sqlite import sqlite_connection_async
from ..utils.runtime import RuntimePaths

logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """
    Unified database initialization manager.

    Responsibilities:
    1. Create all required database tables
    2. Run data migrations
    3. Insert default data
    """

    INIT_MARKER_FILE = ".db_initialized"

    def __init__(self, runtime_paths: RuntimePaths):
        """
        Args:
            runtime_paths: Runtime directory mapping.
        """
        self.runtime_paths = runtime_paths
        self._initializers: List[Callable[[], Awaitable[None]]] = []

    @property
    def is_first_run(self) -> bool:
        """Whether this is the first run (no init marker yet)."""
        return not (self.runtime_paths.runtime_dir / self.INIT_MARKER_FILE).exists()

    def mark_initialized(self) -> None:
        """Mark initialization as complete."""
        marker_file = self.runtime_paths.runtime_dir / self.INIT_MARKER_FILE
        marker_file.touch()
        logger.info(f"Marked database as initialized: {marker_file}")

    def register_initializer(self, initializer: Callable[[], Awaitable[None]]):
        """Register an initializer function."""
        self._initializers.append(initializer)

    async def initialize_all(self) -> None:
        """Run all initialization."""
        # Ensure directories exist
        self.runtime_paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.memory_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.chat_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.resources_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.runtime_dir.mkdir(parents=True, exist_ok=True)

        if self.is_first_run:
            logger.info("=" * 50)
            logger.info("First run detected, initializing databases...")
            logger.info("=" * 50)
            is_first = True
        else:
            logger.info("Databases already initialized, verifying tables...")
            is_first = False

        # 1. Initialize core DB tables (IF NOT EXISTS, idempotent)
        await self._init_message_queue_db()
        await self._init_chat_db()
        await self._init_shared_memory_db()
        await self._init_l1_memory_db()
        await self._init_behavior_evolution_db()
        await self._init_emotional_state_db()
        await self._init_growth_memory_db()

        # 2. Run registered custom initializers
        for initializer in self._initializers:
            try:
                await initializer()
            except Exception as e:
                logger.error(f"Custom initializer failed: {e}")

        if is_first:
            logger.info("Database initialization completed for first run")
        else:
            logger.info("Database verification completed")

    async def _init_message_queue_db(self) -> None:
        """Initialize runtime command queue database."""
        db_path = self.runtime_paths.message_queue_db_path
        async with sqlite_connection_async(str(db_path), use_row_factory=False) as db:
            # runtime_commands table is created lazily by SQLiteRuntimeCommandQueue.
            await db.commit()
        logger.debug(f"Initialized message_queue.db at {db_path}")

    async def _init_chat_db(self) -> None:
        """Initialize dedicated chat database."""
        from ..chat import ChatStore

        db_path = self.runtime_paths.chat_db_path
        store = ChatStore(db_path=str(db_path))
        await store.initialize()
        await store.shutdown()
        logger.debug(f"Initialized chat.db at {db_path}")

    async def _init_shared_memory_db(self) -> None:
        """Initialize shared memory database (L0/L2/L3/L4)."""
        from ..memory.l0.working_memory import L0WorkingMemoryStore
        from ..memory.l2.store import L2CognitionStore
        from ..memory.l3.summary_store import L3SummaryStore
        from ..memory.l4.procedural_memory import L4ProceduralMemoryStore

        db_path = self.runtime_paths.memory_db_path

        l0_store = L0WorkingMemoryStore(checkpoint_db_path=str(db_path))
        l2_store = L2CognitionStore(db_path=str(db_path))
        l3_store = L3SummaryStore(db_path=str(db_path))
        l4_store = L4ProceduralMemoryStore(db_path=str(db_path))

        await l0_store.initialize()
        await l2_store.initialize()
        await l3_store.initialize()
        await l4_store.initialize()
        logger.debug(f"Initialized memory.db at {db_path}")

    async def _init_l1_memory_db(self) -> None:
        """Initialize L1 memory database."""
        from ..memory.l1.event_store import L1EventStore

        db_path = self.runtime_paths.l1_memory_db_path
        store = L1EventStore(db_path=str(db_path))
        await store.initialize()
        logger.debug(f"Initialized l1_events.db at {db_path}")

    async def _init_behavior_evolution_db(self) -> None:
        """Initialize behavior evolution database."""
        db_path = self.runtime_paths.behavior_db_path
        async with sqlite_connection_async(str(db_path), use_row_factory=False) as db:
            # task_interactions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS task_interactions (
                    task_id TEXT PRIMARY KEY,
                    task_category TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    clarification_count INTEGER NOT NULL,
                    confirmation_count INTEGER NOT NULL,
                    correction_count INTEGER NOT NULL,
                    satisfaction TEXT NOT NULL,
                    task_complexity REAL NOT NULL,
                    task_duration REAL NOT NULL,
                    accepted INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_interactions_category
                ON task_interactions(task_category)
            """)

            # category_statistics table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS category_statistics (
                    category TEXT PRIMARY KEY,
                    total_tasks INTEGER NOT NULL,
                    accepted_tasks INTEGER NOT NULL,
                    avg_clarifications REAL NOT NULL,
                    avg_confirmations REAL NOT NULL,
                    avg_corrections REAL NOT NULL,
                    avg_satisfaction REAL NOT NULL,
                    avg_complexity REAL NOT NULL,
                    cautious_score REAL NOT NULL,
                    impatient_score REAL NOT NULL,
                    dense_score REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # behavior_profiles table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS behavior_profiles (
                    task_category TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            await db.commit()
        logger.debug(f"Initialized behavior_evolution.db at {db_path}")

    async def _init_emotional_state_db(self) -> None:
        """Initialize emotional state database."""
        db_path = self.runtime_paths.emotional_db_path
        async with sqlite_connection_async(str(db_path), use_row_factory=False) as db:
            # emotional_state table (key-value)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS emotional_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # emotional_events table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS emotional_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    previous_mood TEXT NOT NULL,
                    new_mood TEXT NOT NULL,
                    mood_delta REAL NOT NULL,
                    energy_delta REAL NOT NULL,
                    stress_delta REAL NOT NULL,
                    cause TEXT NOT NULL
                )
            """)

            # Create index
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_emotional_events_timestamp
                ON emotional_events(timestamp DESC)
            """)

            await db.commit()
        logger.debug(f"Initialized emotional_state.db at {db_path}")

    async def _init_growth_memory_db(self) -> None:
        """Initialize growth memory database."""
        db_path = self.runtime_paths.growth_db_path
        async with sqlite_connection_async(str(db_path), use_row_factory=False) as db:
            # milestones table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS milestones (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata TEXT NOT NULL
                )
            """)

            # relationships table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    user_id TEXT PRIMARY KEY,
                    depth REAL NOT NULL,
                    first_interaction REAL NOT NULL,
                    last_interaction REAL NOT NULL,
                    total_interactions INTEGER NOT NULL,
                    interaction_types TEXT NOT NULL,
                    sentiment_score REAL NOT NULL,
                    trust_level REAL NOT NULL,
                    notes TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # personality_evolution table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS personality_evolution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    aspect TEXT NOT NULL,
                    previous_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL
                )
            """)

            # growth_statistics table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS growth_statistics (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # Create indexes
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_milestones_timestamp
                ON milestones(timestamp DESC)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_updated
                ON relationships(updated_at DESC)
            """)

            await db.commit()
        logger.debug(f"Initialized growth_memory.db at {db_path}")

    async def insert_default_data(self, persona_name: str = "default") -> None:
        """Insert default data (first run only)."""
        if not self.is_first_run:
            logger.info("Skipping default data insertion (not first run)")
            return

        # Mark initialization complete
        _ = persona_name
        self.mark_initialized()


# Global instance
_database_initializer: DatabaseInitializer | None = None


def get_database_initializer() -> DatabaseInitializer:
    """Get the global database initializer instance."""
    return _database_initializer


def set_database_initializer(initializer: DatabaseInitializer) -> None:
    """Set the global database initializer instance."""
    global _database_initializer
    _database_initializer = initializer
