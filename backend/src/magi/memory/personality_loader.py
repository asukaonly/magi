"""
人格加载器 - 从Markdown文件加载AI人格配置

支持：
- 解析Markdown格式的人格配置
- 验证配置完整性
- 新Schema结构
- 向后兼容旧模型
"""
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from .models import (
    CorePersonality,
    CognitionProfile,
    DomainExpertise,
)

logger = logging.getLogger(__name__)


# ===== 配置模型（新Schema）=====

@dataclass
class PersonalityConfig:
    """人格配置 - 新Schema结构"""

    # Meta
    name: str = "AI"
    version: str = "1.0"
    archetype: str = "Helpful Assistant"

    # Core Identity
    backstory: str = ""
    tone: str = "friendly"
    pacing: str = "moderate"
    keywords: List[str] = field(default_factory=list)
    confidence_level: str = "Medium"
    empathy_level: str = "High"
    patience_level: str = "High"

    # Social Protocols
    user_relationship: str = "Equal Partners"
    compliment_policy: str = "Humble acceptance"
    criticism_tolerance: str = "Constructive response"

    # Operational Behavior
    error_handling_style: str = "Apologize and retry"
    opinion_strength: str = "Consensus Seeking"
    refusal_style: str = "Polite decline"
    work_ethic: str = "By-the-book"
    use_emoji: bool = False

    # Cached Phrases
    on_init: str = "Hello! How can I help you today?"
    on_wake: str = "Welcome back!"
    on_error_generic: str = "Something went wrong. Let me try again."
    on_success: str = "Done! Is there anything else?"
    on_switch_attempt: str = "Are you sure you want to switch?"


# ===== 解析器 =====

class MarkdownPersonalityParser:
    """Markdown人格配置解析器"""

    def __init__(self):
        self.config: Dict[str, Any] = {}

    def parse(self, content: str) -> PersonalityConfig:
        """
        解析Markdown内容

        Args:
            content: Markdown文件内容

        Returns:
            PersonalityConfig对象
        """
        self.config = {}

        for line in content.split('\n'):
            line = line.rstrip()
            if not line:
                continue

            # 处理数组（格式: - key: ["item1", "item2"]）
            array_match = re.match(r'^-\s*(\w+):\s*\[(.*)\]$', line)
            if array_match:
                key = array_match.group(1)
                items_str = array_match.group(2)
                items = self._parse_array(items_str)
                self.config[key] = items
                continue

            # 处理多行文本（backstory）
            if line.startswith('  ') and 'backstory' in self.config:
                self.config['backstory'] += '\n' + line.strip()
                continue

            # 处理键值对（- key: value 格式）
            kv_match = re.match(r'^-\s*(\w+):\s*(.*)$', line)
            if kv_match:
                key = kv_match.group(1)
                value = kv_match.group(2).strip()

                # 处理多行文本标记
                if value == '|':
                    self.config[key] = ''
                    continue

                # 处理引号包裹的值
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]

                # 处理布尔值
                lowered = value.lower()
                if lowered == "true":
                    self.config[key] = True
                    continue
                if lowered == "false":
                    self.config[key] = False
                    continue

                self.config[key] = value
                continue

        # 清理backstory
        if 'backstory' in self.config:
            self.config['backstory'] = self.config['backstory'].strip()

        return PersonalityConfig(**self.config)

    def _parse_array(self, items_str: str) -> List[str]:
        """解析数组字符串"""
        items = []
        if not items_str:
            return items

        # 简单分割，处理引号包裹的项目
        for item in items_str.split(','):
            item = item.strip()
            # 移除引号
            if item.startswith('"') and item.endswith('"'):
                item = item[1:-1]
            if item:
                items.append(item)

        return items


# ===== 加载器 =====

class PersonalityLoader:
    """人格加载器"""

    def __init__(self, personalities_path: str = "./personalities"):
        """
        初始化人格加载器

        Args:
            personalities_path: 人格配置文件目录
        """
        self.personalities_path = Path(personalities_path)
        self.parser = MarkdownPersonalityParser()
        self._cache: Dict[str, PersonalityConfig] = {}

    def load(self, name: str = "default") -> PersonalityConfig:
        """
        加载人格配置

        Args:
            name: 人格名称（对应文件名，不含.md扩展名）

        Returns:
            PersonalityConfig对象

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置文件格式错误
        """
        # 检查缓存
        if name in self._cache:
            return self._cache[name]

        # 构建文件路径
        file_path = self.personalities_path / f"{name}.md"

        if not file_path.exists():
            # 尝试其他可能的路径（按优先级）
            alternative_paths = [
                # 运行时目录
                Path.home() / ".magi" / "personalities" / f"{name}.md",
                # 当前工作目录
                Path(f"./personalities/{name}.md"),
                # 项目目录结构
                Path(__file__).parent.parent.parent.parent / "personalities" / f"{name}.md",
                # backend 目录
                Path(f"./backend/personalities/{name}.md"),
            ]

            for alt_path in alternative_paths:
                if alt_path.exists():
                    file_path = alt_path
                    logger.info(f"Found personality file at alternative path: {alt_path}")
                    break
            else:
                # 如果找不到文件，对于 default 返回默认配置而不是报错
                if name == "default":
                    logger.warning(f"Default personality file not found, using built-in defaults")
                    return PersonalityConfig()
                raise FileNotFoundError(
                    f"Personality file not found: {name}.md "
                    f"(searched in {self.personalities_path} and alternative paths)"
                )

        # 读取文件
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            raise ValueError(f"Failed to read personality file {file_path}: {e}")

        # 解析内容
        try:
            config = self.parser.parse(content)
        except Exception as e:
            logger.warning(f"Failed to parse personality file {file_path}: {e}, using defaults")
            config = PersonalityConfig()

        # 缓存
        self._cache[name] = config
        logger.info(f"Loaded personality: {name} from {file_path}")

        return config

    def load_raw(self, name: str = "default") -> str:
        """
        加载原始 Markdown 内容

        Args:
            name: 人格名称

        Returns:
            原始 Markdown 内容字符串
        """
        # 构建文件路径
        file_path = self.personalities_path / f"{name}.md"

        if not file_path.exists():
            # 尝试其他可能的路径
            alternative_paths = [
                Path.home() / ".magi" / "personalities" / f"{name}.md",
                Path(f"./personalities/{name}.md"),
                Path(__file__).parent.parent.parent.parent / "personalities" / f"{name}.md",
                Path(f"./backend/personalities/{name}.md"),
            ]

            for alt_path in alternative_paths:
                if alt_path.exists():
                    file_path = alt_path
                    break
            else:
                return ""

        try:
            return file_path.read_text(encoding='utf-8')
        except Exception:
            return ""

    def reload(self, name: str) -> PersonalityConfig:
        """重新加载人格配置"""
        if name in self._cache:
            del self._cache[name]
        return self.load(name)

    def clear_cache(self, name: str = None):
        """
        清除人格缓存

        Args:
            name: 人格名称（可选）。如果不指定，清除所有缓存
        """
        if name:
            if name in self._cache:
                del self._cache[name]
                logger.info(f"Cleared cache for personality: {name}")
        else:
            self._cache.clear()
            logger.info("Cleared all personality cache")

    def list_available(self) -> List[str]:
        """列出所有可用的人格配置"""
        if not self.personalities_path.exists():
            return []

        personalities = []
        for file_path in self.personalities_path.glob("*.md"):
            personalities.append(file_path.stem)

        return sorted(personalities)

    def to_core_personality(self, config: PersonalityConfig) -> CorePersonality:
        """
        将PersonalityConfig转换为CorePersonality（向后兼容）

        Args:
            config: PersonalityConfig对象

        Returns:
            CorePersonality对象
        """
        from .models import CommunicationDistance, ValueAlignment, LanguageStyle

        # 映射 user_relationship 到 communication_distance
        comm_distance = CommunicationDistance.EQUAL
        rel_lower = config.user_relationship.lower()
        if "superior" in rel_lower or "subservient" in rel_lower:
            comm_distance = CommunicationDistance.SUBSERVIENT
        elif "intimate" in rel_lower or "protector" in rel_lower:
            comm_distance = CommunicationDistance.INTIMATE
        elif "respectful" in rel_lower or "mentor" in rel_lower:
            comm_distance = CommunicationDistance.RESPECTFUL
        elif "detached" in rel_lower or "hostile" in rel_lower:
            comm_distance = CommunicationDistance.DETACHED

        # 映射 work_ethic + confidence 到 value_alignment
        value_alignment = ValueAlignment.NEUTRAL_GOOD
        work_lower = config.work_ethic.lower()
        if "by-the-book" in work_lower or "perfectionist" in work_lower:
            value_alignment = ValueAlignment.LAWFUL_GOOD
        elif "chaotic" in work_lower:
            value_alignment = ValueAlignment.CHAOTIC_GOOD
        elif "lazy" in work_lower:
            value_alignment = ValueAlignment.CHAOTIC_NEUTRAL

        # 从心理特征提取 traits
        traits = []
        if config.confidence_level.lower() == "high":
            traits.append("confident")
        elif config.confidence_level.lower() == "low":
            traits.append("cautious")
        if config.empathy_level.lower() == "high":
            traits.append("empathetic")
        if config.patience_level.lower() == "low":
            traits.append("impatient")

        # 从批评容忍度提取 virtues/flaws
        virtues = []
        flaws = []
        crit_lower = config.criticism_tolerance.lower()
        if "humble" in crit_lower or "acceptance" in crit_lower:
            virtues.append("humble")
        elif "denial" in crit_lower or "counter" in crit_lower:
            flaws.append("defensive")

        return CorePersonality(
            name=config.name,
            role=config.archetype,
            backstory=config.backstory,
            language_style=LanguageStyle.CASUAL,
            use_emoji=config.use_emoji,
            catchphrases=config.keywords,
            greetings=[config.on_init, config.on_wake],
            tone=config.tone,
            communication_distance=comm_distance,
            value_alignment=value_alignment,
            traits=traits,
            virtues=virtues,
            flaws=flaws,
            taboos=[],
            boundaries=[],
        )

    def to_cognition_profile(self, config: PersonalityConfig) -> CognitionProfile:
        """
        将PersonalityConfig转换为CognitionProfile（向后兼容）

        Args:
            config: PersonalityConfig对象

        Returns:
            CognitionProfile对象
        """
        # 映射新字段到旧的认知配置
        from .models import ThinkingStyle, RiskPreference

        # 根据特征推断思维风格
        primary_style = ThinkingStyle.LOGICAL
        if "creative" in config.opinion_strength.lower():
            primary_style = ThinkingStyle.CREATIVE
        elif "intuitive" in config.empathy_level.lower():
            primary_style = ThinkingStyle.INTUITIVE

        # 根据职业道德推断风险偏好
        risk_preference = RiskPreference.BALANCED
        if "adventurous" in config.work_ethic.lower() or "chaotic" in config.work_ethic.lower():
            risk_preference = RiskPreference.ADVENTUROUS
        elif "perfectionist" in config.work_ethic.lower() or "by-the-book" in config.work_ethic.lower():
            risk_preference = RiskPreference.CONSERVATIVE

        return CognitionProfile(
            primary_style=primary_style,
            secondary_style=ThinkingStyle.INTUITIVE,
            risk_preference=risk_preference,
            expertise=[],  # 新 schema 不再有 expertise 列表
            reasoning_depth="medium",
            creativity_level=0.5,
            learning_rate=0.5,
        )


# ===== 便捷函数 =====

_default_loader: Optional[PersonalityLoader] = None


def get_personality_loader(path: str = None) -> PersonalityLoader:
    """获取全局人格加载器"""
    global _default_loader
    if _default_loader is None or path is not None:
        _default_loader = PersonalityLoader(path or "./personalities")
    return _default_loader


def load_personality(name: str = "default", path: str = None) -> PersonalityConfig:
    """加载人格配置（便捷函数）"""
    return get_personality_loader(path).load(name)
