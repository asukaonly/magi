"""
Personality Loader - 从MarkdownfileloadAIPersonality configuration

support：
- parseMarkdownformat的Personality configuration
- ValidateConfigurationintegrity
- New Schemastructure
- 向后compatibleoldmodel
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


# ===== Configurationmodel（New Schema）=====

@dataclass
class PersonalityConfig:
    """Personality Configuration - New Schema structure"""

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

    # operational Behavior
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


# ===== parse器 =====

class MarkdownPersonalityParser:
    """Markdown Personality Configuration Parser"""

    def __init__(self):
        self.config: Dict[str, Any] = {}

    def parse(self, content: str) -> PersonalityConfig:
        """
        parseMarkdownContent

        Args:
            content: MarkdownfileContent

        Returns:
            PersonalityConfigObject
        """
        self.config = {}

        for line in content.split('\n'):
            line = line.rstrip()
            if not line:
                continue

            # processarray（format: - key: ["item1", "item2"]）
            array_match = re.match(r'^-\s*(\w+):\s*\[(.*)\]$', line)
            if array_match:
                key = array_match.group(1)
                items_str = array_match.group(2)
                items = self._parse_array(items_str)
                self.config[key] = items
                continue

            # process多row文本（backstory）
            if line.startswith('  ') and 'backstory' in self.config:
                self.config['backstory'] += '\n' + line.strip()
                continue

            # processkeyValue对（- key: value format）
            kv_match = re.match(r'^-\s*(\w+):\s*(.*)$', line)
            if kv_match:
                key = kv_match.group(1)
                value = kv_match.group(2).strip()

                # process多row文本mark
                if value == '|':
                    self.config[key] = ''
                    continue

                # process引号package裹的Value
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]

                # process布尔Value
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
        """parsearraystring"""
        items = []
        if not items_str:
            return items

        # simple分割，process引号package裹的项目
        for item in items_str.split(','):
            item = item.strip()
            # Remove引号
            if item.startswith('"') and item.endswith('"'):
                item = item[1:-1]
            if item:
                items.append(item)

        return items


# ===== load器 =====

class PersonalityLoader:
    """Personality Loader"""

    def __init__(self, personalities_path: str = "./personalities"):
        """
        initializePersonality Loader

        Args:
            personalities_path: Personality configurationfiledirectory
        """
        self.personalities_path = Path(personalities_path)
        self.parser = MarkdownPersonalityParser()
        self._cache: Dict[str, PersonalityConfig] = {}

    def load(self, name: str = "default") -> PersonalityConfig:
        """
        loadPersonality configuration

        Args:
            name: Personality name（correspondfilename，不含.mdextension名）

        Returns:
            PersonalityConfigObject

        Raises:
            FileNotFoundError: Configurationfilenot found
            ValueError: Configurationfileformaterror
        """
        # checkcache
        if name in self._cache:
            return self._cache[name]

        # buildfilepath
        file_path = self.personalities_path / f"{name}.md"

        if not file_path.exists():
            # 尝试other可能的path（按priority）
            alternative_paths = [
                # run时directory
                Path.home() / ".magi" / "personalities" / f"{name}.md",
                # current工作directory
                path(f"./personalities/{name}.md"),
                # 项目directorystructure
                Path(__file__).parent.parent.parent.parent / "personalities" / f"{name}.md",
                # backend directory
                path(f"./backend/personalities/{name}.md"),
            ]

            for alt_path in alternative_paths:
                if alt_Path.exists():
                    file_path = alt_path
                    logger.info(f"Found personality file at alternative path: {alt_path}")
                    break
            else:
                # 如果找不到file，对于 default Return default configuration而noterror report
                if name == "default":
                    logger.warning(f"Default personality file not found, using built-in defaults")
                    return PersonalityConfig()
                raise FileNotFoundError(
                    f"Personality file not found: {name}.md "
                    f"(searched in {self.personalities_path} and alternative paths)"
                )

        # 读取file
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            raise ValueError(f"Failed to read personality file {file_path}: {e}")

        # parseContent
        try:
            config = self.parser.parse(content)
        except Exception as e:
            logger.warning(f"Failed to parse personality file {file_path}: {e}, using defaults")
            config = PersonalityConfig()

        # cache
        self._cache[name] = config
        logger.info(f"Loaded personality: {name} from {file_path}")

        return config

    def load_raw(self, name: str = "default") -> str:
        """
        load原始 Markdown Content

        Args:
            name: Personality name

        Returns:
            原始 Markdown Contentstring
        """
        # buildfilepath
        file_path = self.personalities_path / f"{name}.md"

        if not file_path.exists():
            # 尝试other可能的path
            alternative_paths = [
                Path.home() / ".magi" / "personalities" / f"{name}.md",
                path(f"./personalities/{name}.md"),
                Path(__file__).parent.parent.parent.parent / "personalities" / f"{name}.md",
                path(f"./backend/personalities/{name}.md"),
            ]

            for alt_path in alternative_paths:
                if alt_Path.exists():
                    file_path = alt_path
                    break
            else:
                return ""

        try:
            return file_path.read_text(encoding='utf-8')
        except Exception:
            return ""

    def reload(self, name: str) -> PersonalityConfig:
        """重newloadPersonality configuration"""
        if name in self._cache:
            del self._cache[name]
        return self.load(name)

    def clear_cache(self, name: str = None):
        """
        清除personalitycache

        Args:
            name: Personality name（optional）。如果不指定，清除allcache
        """
        if name:
            if name in self._cache:
                del self._cache[name]
                logger.info(f"Cleared cache for personality: {name}")
        else:
            self._cache.clear()
            logger.info("Cleared all personality cache")

    def list_available(self) -> List[str]:
        """List all available personalitiesConfiguration"""
        if not self.personalities_Path.exists():
            return []

        personalities = []
        for file_path in self.personalities_path.glob("*.md"):
            personalities.append(file_path.stem)

        return sorted(personalities)

    def to_core_personality(self, config: PersonalityConfig) -> CorePersonality:
        """
        将PersonalityConfigconvert为CorePersonality（向后compatible）

        Args:
            config: PersonalityConfigObject

        Returns:
            CorePersonalityObject
        """
        from .models import CommunicationDistance, ValueAlignment, LanguageStyle

        # mapping user_relationship 到 communication_distance
        comm_distance = CommunicationDistance.EQUAL
        rel_lower = config.user_relationship.lower()
        if "superior" in rel_lower or "subservient" in rel_lower:
            comm_distance = CommunicationDistance.subSERVIENT
        elif "intimate" in rel_lower or "protector" in rel_lower:
            comm_distance = CommunicationDistance.intIMATE
        elif "respectful" in rel_lower or "mentor" in rel_lower:
            comm_distance = CommunicationDistance.RESPECTFUL
        elif "detached" in rel_lower or "hostile" in rel_lower:
            comm_distance = CommunicationDistance.detachED

        # mapping work_ethic + confidence 到 value_alignment
        value_alignment = ValueAlignment.NEUTRAL_GOOD
        work_lower = config.work_ethic.lower()
        if "by-the-book" in work_lower or "perfectionist" in work_lower:
            value_alignment = ValueAlignment.LAWFUL_GOOD
        elif "chaotic" in work_lower:
            value_alignment = ValueAlignment.CHAOTIC_GOOD
        elif "lazy" in work_lower:
            value_alignment = ValueAlignment.CHAOTIC_NEUTRAL

        # 从Psychological profile提取 traits
        traits = []
        if config.confidence_level.lower() == "high":
            traits.append("confident")
        elif config.confidence_level.lower() == "low":
            traits.append("cautious")
        if config.empathy_level.lower() == "high":
            traits.append("empathetic")
        if config.patience_level.lower() == "low":
            traits.append("impatient")

        # 从Criticism tolerance提取 virtues/flaws
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
            language_style=LanguageStyle.CasUAL,
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
        将PersonalityConfigconvert为CognitionProfile（向后compatible）

        Args:
            config: PersonalityConfigObject

        Returns:
            CognitionProfileObject
        """
        # mappingnewfield到old的认知Configuration
        from .models import ThinkingStyle, RiskPreference

        # 根据特征推断思维style
        primary_style = ThinkingStyle.LOGICAL
        if "creative" in config.opinion_strength.lower():
            primary_style = ThinkingStyle.CREATIVE
        elif "intuitive" in config.empathy_level.lower():
            primary_style = ThinkingStyle.intUITIVE

        # 根据Work ethic推断风险preference
        risk_preference = RiskPreference.BALANCED
        if "adventurous" in config.work_ethic.lower() or "chaotic" in config.work_ethic.lower():
            risk_preference = RiskPreference.ADVENTUROUS
        elif "perfectionist" in config.work_ethic.lower() or "by-the-book" in config.work_ethic.lower():
            risk_preference = RiskPreference.CONSERVATIVE

        return CognitionProfile(
            primary_style=primary_style,
            secondary_style=ThinkingStyle.intUITIVE,
            risk_preference=risk_preference,
            expertise=[],  # new schema 不再有 expertise list
            reasoning_depth="medium",
            creativity_level=0.5,
            learning_rate=0.5,
        )


# ===== 便捷Function =====

_default_loader: Optional[PersonalityLoader] = None


def get_personality_loader(path: str = None) -> PersonalityLoader:
    """getglobalPersonality Loader"""
    global _default_loader
    if _default_loader is None or path is not None:
        _default_loader = PersonalityLoader(path or "./personalities")
    return _default_loader


def load_personality(name: str = "default", path: str = None) -> PersonalityConfig:
    """loadPersonality configuration（便捷Function）"""
    return get_personality_loader(path).load(name)
