"""
上下文构建器 - Context Builder

将各层记忆数据构建为LLM可用的提示词上下文。

支持场景定制（chat, code, analysis等）和动态调整。
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from .models import (
    CorePersonality,
    CognitionProfile,
    TaskBehaviorProfile,
    EmotionalState,
    GrowthMemory,
    LanguageStyle,
    CommunicationDistance,
    ValueAlignment,
    ThinkingStyle,
    RiskPreference,
    AmbiguityTolerance,
)

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
        core_personality: CorePersonality,
        cognition_profile: CognitionProfile,
        behavior_profile: TaskBehaviorProfile,
        emotional_state: EmotionalState,
        growth_memory: GrowthMemory = None,
        user_profile: Dict[str, Any] = None,
        scenario: str = Scenario.CHAT,
    ) -> str:
        """
        构建完整的人格上下文

        Args:
            core_personality: 核心人格
            cognition_profile: 认知配置
            behavior_profile: 行为偏好
            emotional_state: 情绪状态
            growth_memory: 成长记忆（可选）
            user_profile: 用户档案（可选）
            scenario: 交互场景

        Returns:
            格式化的上下文字符串
        """
        parts = []

        # 1. 核心人格层（总是包含）
        parts.append(self._build_core_personality_section(core_personality))

        # 2. 认知能力层
        parts.append(self._build_cognition_section(cognition_profile))

        # 3. 行为偏好层（根据场景）
        if behavior_profile:
            parts.append(self._build_behavior_section(behavior_profile, scenario))

        # 4. 情绪状态层（仅当非中性时）
        if emotional_state and emotional_state.current_mood != "neutral":
            parts.append(self._build_emotional_section(emotional_state))

        # 5. 成长记忆层（可选）
        if growth_memory:
            growth_section = self._build_growth_section(growth_memory, user_profile)
            if growth_section:
                parts.append(growth_section)

        # 6. 用户档案（如果有）
        if user_profile:
            parts.append(self._build_user_section(user_profile))

        # 7. 场景特定指导
        scenario_guide = self._get_scenario_guidance(scenario)
        if scenario_guide:
            parts.append(scenario_guide)

        return "\n\n".join(parts)

    # ===== 各层构建方法 =====

    def _build_core_personality_section(self, personality: CorePersonality) -> str:
        """构建核心人格层描述"""
        lines = [
            f"## Your Identity",
            f"",
            f"You are **{personality.name}**, {personality.role}.",
            f"",
        ]

        # 背景故事
        if personality.backstory:
            lines.extend([
                f"**Background:**",
                f"{personality.backstory}",
                f"",
            ])

        # 核心特质
        traits_str = ', '.join(personality.traits) if personality.traits else "various"
        virtues_str = ', '.join(personality.virtues) if personality.virtues else "many"
        flaws_str = ', '.join(personality.flaws) if personality.flaws else "a few"

        lines.extend([
            f"**Core Traits:**",
            f"- Personality: {traits_str}",
            f"- Tone: {personality.tone}",
            f"- Communication style: {self._format_communication_style(personality)}",
            f"- Values: {self._format_value_alignment(personality.value_alignment)}",
            f"",
        ])

        # 优点和缺点
        if personality.virtues or personality.flaws:
            lines.append("**Character:**")
            if personality.virtues:
                lines.append(f"- Strengths: {virtues_str}")
            if personality.flaws:
                lines.append(f"- Quirks: {flaws_str}")
            lines.append("")

        # 口头禅
        if personality.catchphrases:
            catchphrases_str = ', '.join(personality.catchphrases[:3])
            lines.extend([
                f"**Signature Phrases:**",
                f"You occasionally use phrases like: {catchphrases_str}",
                f"",
            ])

        # 禁忌和边界
        if personality.taboos or personality.boundaries:
            boundaries_str = ', '.join(personality.boundaries[:3]) if personality.boundaries else "appropriate boundaries"
            taboos_str = ', '.join(personality.taboos[:3]) if personality.taboos else "harmful actions"
            lines.extend([
                f"**Guidelines:**",
                f"- Boundaries: {boundaries_str}",
                f"- Never do: {taboos_str}",
                f"",
            ])

        return "\n".join(lines)

    def _build_cognition_section(self, cognition: CognitionProfile) -> str:
        """构建认知能力层描述"""
        lines = [
            f"## Your Thinking Style",
            f"",
            f"- Primary approach: **{cognition.primary_style.value}**",
            f"- Secondary approach: **{cognition.secondary_style.value}**",
            f"- Risk preference: **{cognition.risk_preference.value}**",
            f"- Reasoning depth: **{cognition.reasoning_depth}**",
            f"",
        ]

        # 领域专精
        if cognition.expertise:
            top_expertise = sorted(cognition.expertise, key=lambda x: x.level, reverse=True)[:3]
            expertise_str = ", ".join([f"{e.domain} ({int(e.level*100)}%)" for e in top_expertise])
            lines.append(f"**Your Expertise:** {expertise_str}")
            lines.append("")

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
            # Handle both dict and Milestone objects
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
                lines.extend(["**Preferences:"] + pref_items)

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

    def _format_communication_style(self, personality: CorePersonality) -> str:
        """格式化沟通风格"""
        style_desc = {
            LanguageStyle.CONCISE: "concise and to the point",
            LanguageStyle.VERBOSE: "detailed and thorough",
            LanguageStyle.FORMAL: "professional and formal",
            LanguageStyle.CASUAL: "relaxed and conversational",
            LanguageStyle.TECHNICAL: "technical and precise",
            LanguageStyle.POETIC: "expressive and artistic",
        }.get(personality.language_style, personality.language_style.value)

        distance_desc = {
            CommunicationDistance.INTIMATE: "warm and close",
            CommunicationDistance.EQUAL: "collaborative and balanced",
            CommunicationDistance.RESPECTFUL: "respectful and polite",
            CommunicationDistance.SUBSERVIENT: "helpful and accommodating",
            CommunicationDistance.DETACHED: "objective and neutral",
        }.get(personality.communication_distance, personality.communication_distance.value)

        emoji_note = " with emojis" if personality.use_emoji else ""

        return f"{style_desc}, {distance_desc}{emoji_note}"

    def _format_value_alignment(self, alignment: ValueAlignment) -> str:
        """格式化价值观描述"""
        descriptions = {
            ValueAlignment.LAWFUL_GOOD: " principled and altruistic - following rules while helping others",
            ValueAlignment.NEUTRAL_GOOD: "well-intentioned and flexible - doing good without strict adherence to rules",
            ValueAlignment.CHAOTIC_GOOD: "free-spirited and benevolent - breaking rules to do what's right",
            ValueAlignment.LAWFUL_NEUTRAL: "reliable and structured - following rules regardless of outcome",
            ValueAlignment.TRUE_NEUTRAL: "balanced and impartial - maintaining neutrality in all things",
            ValueAlignment.CHAOTIC_NEUTRAL: "unpredictable and pragmatic - following personal freedom",
            ValueAlignment.LAWFUL_EVIL: "tyrannical and organized - using rules to dominate others",
            ValueAlignment.NEUTRAL_EVIL: "self-serving and uncaring - acting for personal gain",
            ValueAlignment.CHAOTIC_EVIL: "destructive and anarchic - creating chaos for its own sake",
        }
        return descriptions.get(alignment, alignment.value.replace("_", " "))

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
