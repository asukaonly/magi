"""
人格加载器 - 从Markdown文件加载AI人格配置

支持：
- 解析Markdown格式的人格配置
- 验证配置完整性
- 转换为CorePersonality和CognitionProfile对象
"""
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .models import (
    CorePersonality,
    CognitionProfile,
    DomainExpertise,
    LanguageStyle,
    CommunicationDistance,
    ValueAlignment,
    ThinkingStyle,
    RiskPreference,
)

logger = logging.getLogger(__name__)


# ===== 配置模型 =====

@dataclass
class PersonalityConfig:
    """人格配置"""
    name: str
    role: str
    backstory: str = ""
    language_style: str = "casual"
    use_emoji: bool = False
    catchphrases: List[str] = None
    tone: str = "friendly"
    communication_distance: str = "equal"
    value_alignment: str = "neutral_good"
    traits: List[str] = None
    virtues: List[str] = None
    flaws: List[str] = None
    taboos: List[str] = None
    boundaries: List[str] = None

    # 认知配置
    primary_style: str = "logical"
    secondary_style: str = "intuitive"
    risk_preference: str = "balanced"
    expertise: Dict[str, float] = None
    reasoning_depth: str = "medium"
    creativity_level: float = 0.5
    learning_rate: float = 0.5

    def __post_init__(self):
        """初始化默认值"""
        if self.catchphrases is None:
            self.catchphrases = []
        if self.traits is None:
            self.traits = []
        if self.virtues is None:
            self.virtues = []
        if self.flaws is None:
            self.flaws = []
        if self.taboos is None:
            self.taboos = []
        if self.boundaries is None:
            self.boundaries = []
        if self.expertise is None:
            self.expertise = {}


# ===== 解析器 =====

class MarkdownPersonalityParser:
    """Markdown人格配置解析器"""

    # 段落解析模式
    PATTERNS = {
        "list_item": re.compile(r"^-\s*(\w+):\s*(.+)$"),
        "key_value": re.compile(r"^(\w+):\s*(.+)$"),
        "array_start": re.compile(r'^(\w+):\s*\[$'),
        "section": re.compile(r"^#+\s+(.+)$"),
    }

    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.current_section: Optional[str] = None
        self.current_array: Optional[tuple[str, List]] = None  # (field_name, items)

    def parse(self, content: str) -> PersonalityConfig:
        """
        解析Markdown内容

        Args:
            content: Markdown文件内容

        Returns:
            PersonalityConfig对象
        """
        self.config = {}
        self.current_section = None
        self.current_array: Optional[tuple[str, List]] = None

        for line in content.split('\n'):
            line = line.rstrip()
            if not line:
                # 空行结束当前数组
                if self.current_array:
                    field_name, items = self.current_array
                    self.config[field_name] = items
                    self.current_array = None
                continue

            # 处理数组结束
            if self.current_array and line == ']':
                field_name, items = self.current_array
                self.config[field_name] = items
                self.current_array = None
                continue

            # 处理数组内容
            if self.current_array:
                field_name, items = self.current_array
                # 移除引号、逗号和闭合括号
                item = line.strip()
                # Remove leading/trailing quotes
                if item.startswith('"'):
                    item = item[1:]
                if item.endswith('"'):
                    item = item[:-1]
                # Remove trailing comma/bracket
                item = item.rstrip(',]').strip()
                if item:
                    items.append(item)
                continue

            # 处理数组开始（格式1: - key: [item1, item2]）
            list_array_match = re.match(r'^-\s*(\w+):\s*\[(.*)$', line)
            if list_array_match:
                key = list_array_match.group(1)
                key = self._normalize_key(key)
                remainder = list_array_match.group(2).strip()
                items = []
                if remainder and remainder != ']':
                    # 单行数组
                    for item in remainder.split(','):
                        item = item.strip()
                        # Remove trailing bracket first
                        item = item.rstrip(']')
                        # Remove quotes
                        if item.startswith('"'):
                            item = item[1:]
                        if item.endswith('"'):
                            item = item[:-1]
                        if item:
                            items.append(item)
                if line.rstrip().endswith(']'):
                    self.config[key] = items
                else:
                    self.current_array = (key, items)
                continue

            # 处理章节标题
            section_match = re.match(r'^#+\s+(.+)$', line)
            if section_match:
                self.current_section = section_match.group(1).lower()
                continue

            # 处理键值对（- key: value 格式）
            kv_match = re.match(r'^-\s*(\w+):\s*(.+)$', line)
            if kv_match:
                key = kv_match.group(1)
                value = self._parse_value(kv_match.group(2))
                # 处理字段名映射
                key = self._normalize_key(key)
                self.config[key] = value
                continue

            # 处理简单键值对（key: value 格式）
            simple_kv_match = re.match(r'^(\w+):\s*(.+)$', line)
            if simple_kv_match:
                key = simple_kv_match.group(1)
                value = self._parse_value(simple_kv_match.group(2))
                # 处理字段名映射
                key = self._normalize_key(key)
                self.config[key] = value
                continue

            # 处理多行文本（背景故事）
            if self.current_section and line and not line.startswith('#'):
                if 'backstory' not in self.config:
                    self.config['backstory'] = ''
                self.config['backstory'] += line + '\n'

        # 解析expertise字典
        if 'expertise' in self.config:
            if isinstance(self.config['expertise'], dict):
                pass  # 已经是字典
            elif isinstance(self.config['expertise'], list):
                # 转换列表为字典
                expertise_dict = {}
                for item in self.config['expertise']:
                    if isinstance(item, str) and ':' in item:
                        domain, level = item.split(':', 1)
                        # Strip whitespace and trailing ]/commas
                        level = level.strip().rstrip(']')
                        try:
                            expertise_dict[domain.strip()] = float(level.strip())
                        except ValueError:
                            # Skip invalid entries
                            pass
                self.config['expertise'] = expertise_dict
            else:
                # 字符串或其他类型，转换为空字典
                self.config['expertise'] = {}

        # 清理backstory
        if 'backstory' in self.config:
            self.config['backstory'] = self.config['backstory'].strip()

        return PersonalityConfig(**self.config)

    def _parse_value(self, value: str) -> Any:
        """解析值类型"""
        value = value.strip()

        # 布尔值
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'

        # 数字
        if value.replace('.', '').isdigit():
            if '.' in value:
                return float(value)
            return int(value)

        # 字符串
        return value

    def _normalize_key(self, key: str) -> str:
        """规范化键名，处理Markdown和代码之间的命名差异"""
        mappings = {
            "style": "language_style",
            "distance": "communication_distance",
            "alignment": "value_alignment",
            "risk": "risk_preference",
            "primary": "primary_style",
            "secondary": "secondary_style",
            "path": "db_path",  # Avoid conflict with pathlib.Path
        }
        return mappings.get(key, key)


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
            # 尝试其他可能的路径
            alternative_paths = [
                Path(f"./personalities/{name}.md"),
                Path(f"./backend/personalities/{name}.md"),
                Path(f"./backend/src/personalities/{name}.md"),
            ]

            for alt_path in alternative_paths:
                if alt_path.exists():
                    file_path = alt_path
                    break
            else:
                raise FileNotFoundError(
                    f"Personality file not found: {name}.md "
                    f"(searched in {self.personalities_path})"
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
            raise ValueError(f"Failed to parse personality file {file_path}: {e}")

        # 验证配置
        self._validate_config(config)

        # 缓存
        self._cache[name] = config
        logger.info(f"Loaded personality: {name} from {file_path}")

        return config

    def reload(self, name: str) -> PersonalityConfig:
        """重新加载人格配置"""
        if name in self._cache:
            del self._cache[name]
        return self.load(name)

    def list_available(self) -> List[str]:
        """列出所有可用的人格配置"""
        if not self.personalities_path.exists():
            return []

        personalities = []
        for file_path in self.personalities_path.glob("*.md"):
            personalities.append(file_path.stem)

        return sorted(personalities)

    def _validate_config(self, config: PersonalityConfig):
        """验证人格配置"""
        required_fields = ['name', 'role']
        missing_fields = [f for f in required_fields if not getattr(config, f, None)]

        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")

        # 验证枚举值
        try:
            LanguageStyle(config.language_style)
        except ValueError:
            raise ValueError(f"Invalid language_style: {config.language_style}")

        try:
            CommunicationDistance(config.communication_distance)
        except ValueError:
            raise ValueError(f"Invalid communication_distance: {config.communication_distance}")

        try:
            ValueAlignment(config.value_alignment)
        except ValueError:
            raise ValueError(f"Invalid value_alignment: {config.value_alignment}")

        try:
            ThinkingStyle(config.primary_style)
        except ValueError:
            raise ValueError(f"Invalid primary_style: {config.primary_style}")

        try:
            ThinkingStyle(config.secondary_style)
        except ValueError:
            raise ValueError(f"Invalid secondary_style: {config.secondary_style}")

        try:
            RiskPreference(config.risk_preference)
        except ValueError:
            raise ValueError(f"Invalid risk_preference: {config.risk_preference}")

        # 验证数值范围
        if not 0 <= config.creativity_level <= 1:
            raise ValueError(f"creativity_level must be between 0 and 1, got {config.creativity_level}")

        if not 0 <= config.learning_rate <= 1:
            raise ValueError(f"learning_rate must be between 0 and 1, got {config.learning_rate}")

    def to_core_personality(self, config: PersonalityConfig) -> CorePersonality:
        """
        将PersonalityConfig转换为CorePersonality

        Args:
            config: PersonalityConfig对象

        Returns:
            CorePersonality对象
        """
        return CorePersonality(
            name=config.name,
            role=config.role,
            backstory=config.backstory,
            language_style=LanguageStyle(config.language_style),
            use_emoji=config.use_emoji,
            catchphrases=config.catchphrases or [],
            tone=config.tone,
            communication_distance=CommunicationDistance(config.communication_distance),
            value_alignment=ValueAlignment(config.value_alignment),
            traits=config.traits or [],
            virtues=config.virtues or [],
            flaws=config.flaws or [],
            taboos=config.taboos or [],
            boundaries=config.boundaries or [],
        )

    def to_cognition_profile(self, config: PersonalityConfig) -> CognitionProfile:
        """
        将PersonalityConfig转换为CognitionProfile

        Args:
            config: PersonalityConfig对象

        Returns:
            CognitionProfile对象
        """
        # 转换expertise字典为DomainExpertise列表
        expertise_list = []
        if config.expertise:
            for domain, level in config.expertise.items():
                expertise_list.append(DomainExpertise(
                    domain=domain,
                    level=min(1.0, max(0.0, float(level))),
                    confidence=0.5,
                ))

        return CognitionProfile(
            primary_style=ThinkingStyle(config.primary_style),
            secondary_style=ThinkingStyle(config.secondary_style),
            risk_preference=RiskPreference(config.risk_preference),
            expertise=expertise_list,
            reasoning_depth=config.reasoning_depth,
            creativity_level=config.creativity_level,
            learning_rate=config.learning_rate,
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
