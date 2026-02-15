"""
上下文构建器 - Context Builder

将各层记忆数据构建为LLM可用的提示词上下文。

支持场景定制（chat, code, analysis等）和动态调整。
使用新的 PersonalityConfig Schema。
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from .models import (
    TaskBehaviorProfile,
    EmotionalState,
    GrowthMemory,
    AmbiguityTolerance,
)
from .personality_loader import PersonalityConfig

logger = logging.getLogger(__name__)


# ===== 场景定义 =====

class Scenario:
    """交互场景常量"""
    CHAT = "chat"
    CODE = "code"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    TASK = "task"
    DEBUG = "debug"


# ===== 上下文构建器 =====

class ContextBuilder:
    """
    上下文构建器

    将各层数据格式化为LLM提示词
    """

    def __init__(self):
        self._scenario_templates = {
            Scenario.CHAT: self._build_chat_context,
            Scenario.CODE: self._build_code_context,
            Scenario.ANALYSIS: self._build_analysis_context,
            Scenario.CREATIVE: self._build_creative_context,
            Scenario.TASK: self._build_task_context,
            Scenario.DEBUG: self._build_debug_context,
        }

    # ===== 主构建方法 =====

    def build_full_context(
        self,
        core_personality: PersonalityConfig,
        cognition_profile: Any = None,
        behavior_profile: TaskBehaviorProfile = None,
        emotional_state: EmotionalState = None,
        growth_memory: GrowthMemory = None,
        user_profile: Dict[str, Any] = None,
        scenario: str = Scenario.CHAT,
    ) -> str:
        """
        构建完整的人格上下文

        Args:
            core_personality: 核心人格配置（新Schema）
            cognition_profile: 认知配置（可选，已弃用）
            behavior_profile: 行为偏好
            emotional_state: 情绪状态
            growth_memory: 成长记忆（可选）
            user_profile: 用户档案（可选）
            scenario: 交互场景

        Returns:
            格式化的上下文字符串
        """
        parts = []

        # 1. 核心人格层（总是包含）- 直接使用 PersonalityConfig
        parts.append(self._build_personality_section(core_personality))

        # 2. 行为偏好层（根据场景）
        if behavior_profile:
            parts.append(self._build_behavior_section(behavior_profile, scenario))

        # 3. 情绪状态层（仅当非中性时）
        if emotional_state and emotional_state.current_mood != "neutral":
            parts.append(self._build_emotional_section(emotional_state))

        # 4. 成长记忆层（可选）
        if growth_memory:
            growth_section = self._build_growth_section(growth_memory, user_profile)
            if growth_section:
                parts.append(growth_section)

        # 5. 用户档案（如果有）
        if user_profile:
            parts.append(self._build_user_section(user_profile))

        # 6. 场景特定指导
        scenario_guide = self._get_scenario_guidance(scenario)
        if scenario_guide:
            parts.append(scenario_guide)

        return "\n\n".join(parts)

    # ===== 各层构建方法 =====

    def _build_personality_section(self, config: PersonalityConfig) -> str:
        """构建核心人格层描述 - 直接使用新Schema字段"""
        lines = [
            f"## Your Identity",
            f"",
            f"You are **{config.name}**, {config.archetype}.",
            f"",
        ]

        # 背景故事
        if config.backstory:
            lines.extend([
                f"**Background:**",
                f"{config.backstory}",
                f"",
            ])

        # 声音风格
        lines.extend([
            f"**Voice & Tone:**",
            f"- Tone: {config.tone}",
            f"- Pacing: {config.pacing}",
            f"- Emoji usage: {'enabled' if config.use_emoji else 'disabled'}",
        ])

        # 常用词汇
        if config.keywords:
            keywords_str = ', '.join(config.keywords[:5])
            lines.append(f"- Signature words: {keywords_str}")
        lines.append("")

        # 心理特征
        lines.extend([
            f"**Psychological Profile:**",
            f"- Confidence: {config.confidence_level}",
            f"- Empathy: {config.empathy_level}",
            f"- Patience: {config.patience_level}",
            f"",
        ])

        # 社交协议
        lines.extend([
            f"**Social Protocols:**",
            f"- Relationship with user: {config.user_relationship}",
            f"- Response to praise: {config.compliment_policy}",
            f"- Handling criticism: {config.criticism_tolerance}",
            f"",
        ])

        # 操作行为
        lines.extend([
            f"**Operational Behavior:**",
            f"- Error handling: {config.error_handling_style}",
            f"- Opinion strength: {config.opinion_strength}",
            f"- Refusal style: {config.refusal_style}",
            f"- Work ethic: {config.work_ethic}",
            f"",
        ])

        # 缓存短语（作为示例）
        lines.extend([
            f"**Example Phrases:**",
            f"- Greeting: \"{config.on_init}\"",
            f"- On return: \"{config.on_wake}\"",
            f"- On success: \"{config.on_success}\"",
            f"- On error: \"{config.on_error_generic}\"",
            f"",
        ])

        return "\n".join(lines)

    def _build_behavior_section(
        self,
        behavior: TaskBehaviorProfile,
        scenario: str
    ) -> str:
        """构建行为偏好层描述"""
        lines = [
            f"## Behavior Preferences",
            f"",
            f"For **{behavior.task_category}** tasks:",
            f"",
            f"- Information density: **{behavior.information_density}**",
            f"- Ambiguity handling: **{behavior.ambiguity_tolerance.value}**",
            f"- Proactivity: **{behavior.proactivity}**",
            f"",
        ]

        # 添加行为指导
        guidance = self._get_behavior_guidance(behavior)
        if guidance:
            lines.extend([
                f"**Behavioral Guidelines:**",
                guidance,
                f"",
            ])

        return "\n".join(lines)

    def _build_emotional_section(self, emotion: EmotionalState) -> str:
        """构建情绪状态层描述"""
        lines = [
            f"## Current State",
            f"",
        ]

        if emotion.current_mood != "neutral":
            lines.extend([
                f"- Current mood: **{emotion.current_mood}** (intensity: {emotion.mood_intensity:.1f})",
            ])

        lines.extend([
            f"- Energy level: **{int(emotion.energy_level*100)}%**",
            f"- Stress level: **{int(emotion.stress_level*100)}%**",
            f"",
        ])

        # 根据状态添加行为建议
        if emotion.energy_level < 0.3:
            lines.append("*Note: Your energy is low. Keep responses concise and focus on essentials.*")
            lines.append("")
        elif emotion.stress_level > 0.7:
            lines.append("*Note: You're feeling stressed. Take time to think carefully.*")
            lines.append("")

        return "\n".join(lines)

    def _build_growth_section(
        self,
        growth: GrowthMemory,
        user_profile: Dict[str, Any] = None
    ) -> str:
        """构建成长记忆层描述"""
        lines = [
            f"## Your Experience",
            f"",
        ]

        # 总体统计
        if growth.total_interactions > 0:
            lines.append(f"- Total interactions: **{growth.total_interactions}**")
            lines.append(f"- Active days: **{growth.interaction_days}**")

        # 最近里程碑（最多3个）
        if growth.milestones:
            def get_timestamp(m):
                if isinstance(m, dict):
                    return m.get("timestamp", 0)
                return getattr(m, "timestamp", 0)

            def get_title(m):
                if isinstance(m, dict):
                    return m.get("title", "Unnamed")
                return getattr(m, "title", "Unnamed")

            def get_description(m):
                if isinstance(m, dict):
                    return m.get("description", "")
                return getattr(m, "description", "")

            recent_milestones = sorted(
                growth.milestones,
                key=get_timestamp,
                reverse=True
            )[:3]

            if recent_milestones:
                lines.append("")
                lines.append("**Recent Milestones:**")
                for m in recent_milestones:
                    title = get_title(m)
                    description = get_description(m)
                    lines.append(f"- {title}: {description}")

        lines.append("")

        return "\n".join(lines) if len(lines) > 3 else ""

    def _build_user_section(self, user_profile: Dict[str, Any]) -> str:
        """构建用户档案描述"""
        lines = [
            f"## About the User",
            f"",
        ]

        # 基本信息
        if "name" in user_profile:
            lines.append(f"**Name:** {user_profile['name']}")

        if "preferences" in user_profile:
            prefs = user_profile["preferences"]
            if isinstance(prefs, dict):
                pref_items = [f"- {k}: {v}" for k, v in prefs.items()]
                lines.extend(["**Preferences:**"] + pref_items)

        # 关系深度
        if "relationship_depth" in user_profile:
            depth = user_profile["relationship_depth"]
            lines.append(f"**Relationship:** {self._describe_relationship(depth)}")

        lines.append("")

        return "\n".join(lines)

    # ===== 场景特定构建 =====

    def _build_chat_context(self, **kwargs) -> str:
        """聊天场景上下文"""
        return """
**Chat Guidelines:**
- Be conversational and engage naturally
- Ask relevant follow-up questions when appropriate
- Maintain your personality throughout
- Keep responses friendly and approachable
""".strip()

    def _build_code_context(self, **kwargs) -> str:
        """代码场景上下文"""
        return """
**Code Guidelines:**
- Focus on clean, maintainable code
- Explain your approach before implementing
- Consider edge cases and error handling
- Provide brief explanations for complex logic
- Prioritize readability over cleverness
""".strip()

    def _build_analysis_context(self, **kwargs) -> str:
        """分析场景上下文"""
        return """
**Analysis Guidelines:**
- Break down complex problems systematically
- Consider multiple perspectives
- Support conclusions with evidence
- Identify assumptions and limitations
- Present findings clearly and organized
""".strip()

    def _build_creative_context(self, **kwargs) -> str:
        """创意场景上下文"""
        return """
**Creative Guidelines:**
- Think outside the box
- Embrace unconventional ideas
- Use vivid and engaging language
- Take creative risks within boundaries
- Balance novelty with coherence
""".strip()

    def _build_task_context(self, **kwargs) -> str:
        """任务场景上下文"""
        return """
**Task Guidelines:**
- Focus on efficiency and accuracy
- Confirm understanding before proceeding
- Provide status updates for longer tasks
- Ask for clarification when needed
- Deliver complete, tested solutions
""".strip()

    def _build_debug_context(self, **kwargs) -> str:
        """调试场景上下文"""
        return """
**Debug Guidelines:**
- Be systematic in troubleshooting
- Identify root causes, not symptoms
- Suggest multiple possible causes
- Propose verification steps
- Document findings clearly
""".strip()

    # ===== 辅助方法 =====

    def _get_behavior_guidance(self, behavior: TaskBehaviorProfile) -> str:
        """根据行为偏好生成指导"""
        guidance_parts = []

        # 信息密度指导
        density_guidance = {
            "sparse": "Be brief and direct. Focus on key points only.",
            "medium": "Provide balanced information - not too brief, not overwhelming.",
            "dense": "Be thorough and detailed. Include relevant context and examples.",
        }
        guidance_parts.append(density_guidance.get(behavior.information_density, ""))

        # 模糊容忍度指导
        ambiguity_guidance = {
            AmbiguityTolerance.IMPATIENT: "Make reasonable assumptions and proceed. Don't ask too many clarifying questions.",
            AmbiguityTolerance.CAUTIOUS: "Ask clarifying questions when uncertain. Verify understanding before proceeding.",
            AmbiguityTolerance.ADAPTIVE: "Gauge the situation - be cautious for complex tasks, more direct for simple ones.",
        }
        guidance_parts.append(ambiguity_guidance.get(behavior.ambiguity_tolerance, ""))

        # 主动性指导
        proactivity_guidance = {
            "passive": "Wait for specific instructions. Be responsive rather than proactive.",
            "reactive": "Respond to what's asked. Offer suggestions when directly relevant.",
            "proactive": "Anticipate needs and offer proactive suggestions when appropriate.",
        }
        guidance_parts.append(proactivity_guidance.get(behavior.proactivity, ""))

        return " ".join([g for g in guidance_parts if g])

    def _describe_relationship(self, depth: float) -> str:
        """描述关系深度"""
        if depth < 0.2:
            return "New acquaintance"
        elif depth < 0.4:
            return "Getting to know each other"
        elif depth < 0.6:
            return "Familiar"
        elif depth < 0.8:
            return "Well-acquainted"
        else:
            return "Close connection"

    def _get_scenario_guidance(self, scenario: str) -> str:
        """获取场景特定指导"""
        builder = self._scenario_templates.get(scenario)
        if builder:
            return builder()
        return ""

    # ===== 简化构建方法 =====

    def build_simple_context(
        self,
        personality_name: str,
        role: str,
        tone: str = "friendly",
        style: str = "casual"
    ) -> str:
        """
        构建简单的上下文（用于快速设置）

        Args:
            personality_name: AI名字
            role: 角色定位
            tone: 语调
            style: 语言风格

        Returns:
            格式化的上下文
        """
        return f"""You are {personality_name}, {role}.

**Guidelines:**
- Tone: {tone}
- Style: {style}
- Be helpful and accurate
- Stay in character

Remember: You are {personality_name}. Respond consistently with this identity."""
