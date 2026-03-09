"""
Database Initializer - 统一的数据库初始化管理器

在应用启动时统一初始化所有数据库表结构。
"""
import asyncio
import logging
import aiosqlite
from pathlib import Path
from typing import List, Callable, Awaitable

logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """
    统一的数据库初始化管理器

    负责：
    1. 创建所有必要的数据库表
    2. 执行数据迁移
    3. 插入默认数据
    """

    INIT_MARKER_FILE = ".db_initialized"

    def __init__(self, data_dir):
        """
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir)
        self.memories_dir = self.data_dir / "memories"
        self._initializers: List[Callable[[], Awaitable[None]]] = []

    @property
    def is_first_run(self) -> bool:
        """判断是否初次启动"""
        return not (self.data_dir / self.INIT_MARKER_FILE).exists()

    def mark_initialized(self) -> None:
        """标记已初始化完成"""
        marker_file = self.data_dir / self.INIT_MARKER_FILE
        marker_file.touch()
        logger.info(f"Marked database as initialized: {marker_file}")

    def register_initializer(self, initializer: Callable[[], Awaitable[None]]):
        """注册一个初始化函数"""
        self._initializers.append(initializer)

    async def initialize_all(self) -> None:
        """执行所有初始化"""
        # 确保目录存在
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

        # 1. 初始化核心数据库表（使用 IF NOT EXISTS，幂等操作）
        await self._init_events_db()
        await self._init_tasks_db()
        await self._init_behavior_evolution_db()
        await self._init_emotional_state_db()
        await self._init_growth_memory_db()
        await self._init_scenario_prompts_db()
        await self._init_embeddings_db()
        await self._init_summaries_db()
        await self._init_capabilities_db()
        await self._init_llm_usage_db()

        # 2. 执行注册的自定义初始化器
        for initializer in self._initializers:
            try:
                await initializer()
            except Exception as e:
                logger.error(f"Custom initializer failed: {e}")

        if is_first:
            logger.info("Database initialization completed for first run")
        else:
            logger.info("Database verification completed")

    async def _init_events_db(self) -> None:
        """初始化事件数据库"""
        db_path = self.data_dir / "events.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # event_store 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_store (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    media_path TEXT,
                    timestamp REAL NOT NULL,
                    source TEXT,
                    level INTEGER,
                    correlation_id TEXT,
                    metadata TEXT,
                    created_at REAL NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_store_type ON event_store(type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_store_timestamp ON event_store(timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_store_correlation ON event_store(correlation_id)")

            # message_queue 表（由 SQLiteMessageBackend 管理）
            await db.commit()
        logger.debug(f"Initialized events.db at {db_path}")

    async def _init_tasks_db(self) -> None:
        """初始化任务数据库"""
        db_path = self.data_dir / "tasks.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    payload TEXT,
                    result TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    parent_task_id TEXT,
                    metadata TEXT
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type)")
            await db.commit()
        logger.debug(f"Initialized tasks.db at {db_path}")

    async def _init_behavior_evolution_db(self) -> None:
        """初始化行为演化数据库"""
        db_path = self.memories_dir / "behavior_evolution.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # task_interactions 表
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

            # category_statistics 表
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

            # behavior_profiles 表
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
        """初始化情绪状态数据库"""
        db_path = self.memories_dir / "emotional_state.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # emotional_state 表 (key-value 结构)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS emotional_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # emotional_events 表
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

            # 创建索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_emotional_events_timestamp
                ON emotional_events(timestamp DESC)
            """)

            await db.commit()
        logger.debug(f"Initialized emotional_state.db at {db_path}")

    async def _init_growth_memory_db(self) -> None:
        """初始化成长记忆数据库"""
        db_path = self.memories_dir / "growth_memory.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # milestones 表
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

            # relationships 表
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

            # personality_evolution 表
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

            # growth_statistics 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS growth_statistics (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # 创建索引
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
        """初始化场景提示词数据库"""
        db_path = self.memories_dir / "scenario_prompts.db"
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

    async def _init_embeddings_db(self) -> None:
        """初始化嵌入向量数据库"""
        db_path = self.memories_dir / "embeddings.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_embeddings (
                    event_id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL
                )
            """)
            await db.commit()
        logger.debug(f"Initialized embeddings.db at {db_path}")

    async def _init_summaries_db(self) -> None:
        """初始化摘要数据库"""
        db_path = self.memories_dir / "summaries.db"
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    summary_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    summary_type TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    event_count INTEGER NOT NULL,
                    key_topics TEXT,
                    created_at REAL NOT NULL
                )
            """)
            await db.commit()
        logger.debug(f"Initialized summaries.db at {db_path}")

    async def _init_capabilities_db(self) -> None:
        """初始化能力记忆数据库"""
        db_path = self.memories_dir / "capabilities.db"
        async with aiosqlite.connect(str(db_path)) as db:
            # capabilities 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    capability_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT NOT NULL,
                    proficiency REAL NOT NULL,
                    usage_count INTEGER NOT NULL,
                    success_count INTEGER NOT NULL,
                    last_used REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # capability_blacklist 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS capability_blacklist (
                    capability_id TEXT PRIMARY KEY,
                    reason TEXT,
                    blacklisted_at REAL NOT NULL
                )
            """)

            # capability_task_stats 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS capability_task_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability_id TEXT NOT NULL,
                    task_category TEXT NOT NULL,
                    usage_count INTEGER NOT NULL,
                    success_count INTEGER NOT NULL,
                    avg_satisfaction REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            await db.commit()
        logger.debug(f"Initialized capabilities.db at {db_path}")

    async def _init_llm_usage_db(self) -> None:
        """初始化 LLM usage 统计数据库"""
        db_path = self.memories_dir / "llm_usage.db"
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
        """插入默认数据（仅初次启动时）"""
        if not self.is_first_run:
            logger.info("Skipping default data insertion (not first run)")
            return

        from ..memory.scenario_prompts import DEFAULT_SCENARIO_PROMPTS

        db_path = self.memories_dir / "scenario_prompts.db"
        async with aiosqlite.connect(str(db_path)) as db:
            import time

            inserted_count = 0
            for (persona, scenario), prompt in DEFAULT_SCENARIO_PROMPTS.items():
                # 只插入 default 和当前人格的提示词
                if persona == "default" or persona == persona_name:
                    # 检查是否已存在
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

        # 标记初始化完成
        self.mark_initialized()


# 全局实例
_database_initializer: DatabaseInitializer | None = None


def get_database_initializer() -> DatabaseInitializer:
    """获取全局数据库初始化器实例"""
    return _database_initializer


def set_database_initializer(initializer: DatabaseInitializer) -> None:
    """设置全局数据库初始化器实例"""
    global _database_initializer
    _database_initializer = initializer
