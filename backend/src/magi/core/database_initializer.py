"""
Database Initializer - unified database initialization manager.

Initializes all database tables on application startup.
"""
import logging
import aiosqlite
from pathlib import Path
from typing import List, Callable, Awaitable

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

    def __init__(self, data_dir):
        """
        Args:
            data_dir: Data directory path.
        """
        self.data_dir = Path(data_dir)
        self.memories_dir = self.data_dir / "memories"
        self._initializers: List[Callable[[], Awaitable[None]]] = []

    @property
    def is_first_run(self) -> bool:
        """Whether this is the first run (no init marker yet)."""
        return not (self.data_dir / self.INIT_MARKER_FILE).exists()

    def mark_initialized(self) -> None:
        """Mark initialization as complete."""
        marker_file = self.data_dir / self.INIT_MARKER_FILE
        marker_file.touch()
        logger.info(f"Marked database as initialized: {marker_file}")

    def register_initializer(self, initializer: Callable[[], Awaitable[None]]):
        """Register an initializer function."""
        self._initializers.append(initializer)

    async def initialize_all(self) -> None:
        """Run all initialization."""
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)

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
        await self._init_shared_memory_db()
        await self._init_l1_memory_db()
        await self._init_behavior_evolution_db()
        await self._init_emotional_state_db()
        await self._init_growth_memory_db()
        await self._init_scenario_prompts_db()
        await self._init_llm_usage_db()

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
        """Initialize message bus database."""
        db_path = self.data_dir / "message_queue.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # message_queue table is managed by SQLiteMessageBackend.
            await db.execute("PRAGMA journal_mode=WAL")
            await db.commit()
        logger.debug(f"Initialized message_queue.db at {db_path}")

    async def _init_shared_memory_db(self) -> None:
        """Initialize shared memory database (L0/L2/L3/L4)."""
        from ..memory.l0_working_memory import L0WorkingMemoryStore
        from ..memory.l2_cognition_store import L2CognitionStore
        from ..memory.l3_summary_store import L3SummaryStore
        from ..memory.l4_procedural_memory import L4ProceduralMemoryStore

        db_path = self.memories_dir / "memory.db"

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
        from ..memory.l1_event_store import L1EventStore

        db_path = self.memories_dir / "l1_events.db"
        store = L1EventStore(db_path=str(db_path))
        await store.initialize()
        logger.debug(f"Initialized l1_events.db at {db_path}")

    async def _init_behavior_evolution_db(self) -> None:
        """Initialize behavior evolution database."""
        db_path = self.memories_dir / "behavior_evolution.db"
        async with aiosqlite.connect(str(db_path)) as db:
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
        db_path = self.memories_dir / "emotional_state.db"
        async with aiosqlite.connect(str(db_path)) as db:
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
        db_path = self.memories_dir / "growth_memory.db"
        async with aiosqlite.connect(str(db_path)) as db:
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

    async def _init_scenario_prompts_db(self) -> None:
        """Initialize scenario prompts database."""
        db_path = self.data_dir / "scenario_prompts.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scenario_prompts (
                    persona TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (persona, scenario)
                )
            """)
            await db.commit()
        logger.debug(f"Initialized scenario_prompts.db at {db_path}")

    async def _init_llm_usage_db(self) -> None:
        """Initialize LLM usage statistics database."""
        db_path = self.data_dir / "llm_usage.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    request_kind TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_available INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    correlation_id TEXT,
                    session_id TEXT,
                    turn_id TEXT,
                    agent_id TEXT,
                    created_at REAL NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage(created_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_provider_model ON llm_usage(provider, model)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_request_kind ON llm_usage(request_kind)"
            )
            await db.commit()
        logger.debug(f"Initialized llm_usage.db at {db_path}")

    async def insert_default_data(self, persona_name: str = "default") -> None:
        """Insert default data (first run only)."""
        if not self.is_first_run:
            logger.info("Skipping default data insertion (not first run)")
            return

        from ..memory.scenario_prompts import DEFAULT_SCENARIO_PROMPTS

        db_path = self.data_dir / "scenario_prompts.db"
        async with aiosqlite.connect(str(db_path)) as db:
            import time

            inserted_count = 0
            for (persona, scenario), prompt in DEFAULT_SCENARIO_PROMPTS.items():
                # Only insert default and current persona prompts
                if persona == "default" or persona == persona_name:
                    # Check if already exists
                    cursor = await db.execute(
                        "SELECT 1 FROM scenario_prompts WHERE persona = ? AND scenario = ?",
                        (persona, scenario)
                    )
                    if not await cursor.fetchone():
                        now = time.time()
                        await db.execute(
                            "INSERT INTO scenario_prompts (persona, scenario, prompt, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                            (persona, scenario, prompt, now, now)
                        )
                        logger.info(f"Inserted default scenario prompt: {persona}/{scenario}")
                        inserted_count += 1

            await db.commit()

            if inserted_count > 0:
                logger.info(f"Inserted {inserted_count} default scenario prompts")

        # Mark initialization complete
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
