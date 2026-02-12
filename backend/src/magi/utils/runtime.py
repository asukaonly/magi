"""
运行时数据目录管理

将所有运行时生成的数据统一放到 ~/.magi 目录下，与代码分离
"""
import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class RuntimePaths:
    """运行时路径管理"""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        初始化运行时路径

        Args:
            base_dir: 基础目录，默认为 ~/.magi
        """
        if base_dir is None:
            # 使用用户主目录下的 .magi 文件夹
            home = Path.home()
            base_dir = home / ".magi"

        self.base_dir = Path(base_dir)
        self._ensure_directories()

    def _ensure_directories(self):
        """确保所有必要的目录存在"""
        directories = [
            self.base_dir,
            self.personalities_dir,
            self.data_dir,
            self.memories_dir,
            self.others_dir,  # 他人记忆目录
            self.logs_dir,
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

        logger.info(f"Runtime directory: {self.base_dir}")

    @property
    def personalities_dir(self) -> Path:
        """人格配置目录"""
        return self.base_dir / "personalities"

    @property
    def data_dir(self) -> Path:
        """数据目录"""
        return self.base_dir / "data"

    @property
    def memories_dir(self) -> Path:
        """记忆数据库目录"""
        return self.data_dir / "memories"

    @property
    def others_dir(self) -> Path:
        """他人记忆目录（MD文件存储）"""
        return self.base_dir / "others"

    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return self.base_dir / "logs"

    @property
    def behavior_db_path(self) -> Path:
        """行为演化数据库路径"""
        return self.memories_dir / "behavior_evolution.db"

    @property
    def emotional_db_path(self) -> Path:
        """情绪状态数据库路径"""
        return self.memories_dir / "emotional_state.db"

    @property
    def growth_db_path(self) -> Path:
        """成长记忆数据库路径"""
        return self.memories_dir / "growth_memory.db"

    @property
    def self_memory_db_path(self) -> Path:
        """自我记忆数据库路径（兼容）"""
        return self.memories_dir / "self_memory_v2.db"

    @property
    def events_db_path(self) -> Path:
        """事件数据库路径"""
        return self.data_dir / "events.db"

    def other_file(self, user_id: str) -> Path:
        """
        获取他人记忆文件路径

        Args:
            user_id: 用户ID

        Returns:
            他人记忆MD文件路径
        """
        # 将用户ID转成安全的文件名（替换特殊字符）
        safe_name = user_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.others_dir / f"{safe_name}.md"

    def personality_file(self, name: str) -> Path:
        """
        获取人格配置文件路径

        Args:
            name: 人格名称（不含扩展名）

        Returns:
            人格配置文件完整路径
        """
        return self.personalities_dir / f"{name}.md"

    def get_personality_path(self, name: str = "default") -> str:
        """
        获取人格配置文件路径（字符串格式，用于兼容）

        Args:
            name: 人格名称

        Returns:
            人格目录路径字符串
        """
        return str(self.personalities_dir)

    def initialize_default_personality(self):
        """
        初始化默认人格配置

        如果运行时目录中没有 default.md，从代码目录复制一份
        同时确保 current 文件存在（记录当前使用的人格）
        """
        # 复制 default.md 模板（如果不存在）
        default_file = self.personality_file("default")

        if not default_file.exists():
            # 尝试从代码目录复制
            possible_sources = [
                Path("./personalities/default.md"),
                Path("./backend/personalities/default.md"),
                Path(__file__).parent.parent.parent.parent / "personalities" / "default.md",
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

        # 确保 current 文件存在
        current_file = self.personalities_dir / "current"
        if not current_file.exists():
            # 尝试从现有的 .md 文件中选择一个人格作为默认
            md_files = list(self.personalities_dir.glob("*.md"))
            valid_personalities = [f.stem for f in md_files if f.stem != "default"]

            if valid_personalities:
                # 使用第一个人格作为默认
                current_file.write_text(valid_personalities[0])
                logger.info(f"Created current file with personality: {valid_personalities[0]}")
            else:
                # 如果没有自定义人格，使用 default
                current_file.write_text("default")
                logger.info("Created current file with default personality")
        else:
            current_name = current_file.read_text().strip()
            logger.info(f"Current personality: {current_name}")

    @property
    def current_personality_file(self) -> Path:
        """获取当前人格文件的路径"""
        current_file = self.personalities_dir / "current"
        if current_file.exists():
            name = current_file.read_text().strip()
        else:
            name = "default"
        return self.personality_file(name)


# 全局实例
_runtime_paths: Optional[RuntimePaths] = None


def get_runtime_paths() -> RuntimePaths:
    """获取全局运行时路径实例"""
    global _runtime_paths
    if _runtime_paths is None:
        _runtime_paths = RuntimePaths()
    return _runtime_paths


def set_runtime_dir(path: str | Path):
    """
    设置自定义运行时目录

    Args:
        path: 自定义目录路径
    """
    global _runtime_paths
    _runtime_paths = RuntimePaths(Path(path))


def init_runtime_data():
    """
    初始化运行时数据

    在应用启动时调用，确保默认配置存在
    """
    paths = get_runtime_paths()
    paths.initialize_default_personality()
