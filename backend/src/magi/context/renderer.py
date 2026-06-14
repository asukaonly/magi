"""Renderer for modular LLM prompt contexts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from ..personality.turn_planner import PersonaTurnPlan
from .schema import (
    ProfileMemoryContext,
    PromptAssemblyContext,
    RetrievalMemoryContext,
    RuntimeSystemContext,
    ToolCatalogContext,
)


class PromptContextRenderer:
    """Renders modular prompt contexts into final system prompt text."""

    def render_system_prompt(self, context: PromptAssemblyContext, *, include_tool_catalog: bool = True) -> str:
        lines: List[str] = []

        lines.extend([
            "# System Definition",
            context.identity_constraints.system_definition,
            "",
            "## Core Truths & Boundaries",
            context.identity_constraints.core_truths_and_boundaries,
            "",
        ])

        # Cache-prefix ordering (issue #97): prompt caching is a prefix match,
        # so the byte-stable blocks are emitted first to maximise the cacheable
        # head of the request, and the per-turn dynamic blocks follow. Identity
        # is already first; the tool catalog (stable when the selected tool set
        # is unchanged) is rendered next, ahead of the persona plan / memory /
        # runtime blocks that change every turn.
        if include_tool_catalog:
            # The "You MUST use the available tools" block frames the turn as
            # a task to complete. In emotional / crisis registers that frame
            # is actively wrong — pushing a model in those states toward
            # tool execution makes it skip acknowledgement and jump to
            # solutions. The tool catalog itself stays visible so the model
            # can still call tools when genuinely needed; only the imperative
            # framing is dropped.
            register = (
                getattr(context.self_memory.persona_turn_plan, "register", None)
                if context.self_memory.persona_turn_plan
                else None
            )
            suppress_tool_imperatives = register in {"emotional", "crisis"}
            lines.extend(self._render_tool_catalog(
                context.tool_catalog,
                suppress_imperatives=suppress_tool_imperatives,
            ))

        # Only the byte-stable persona DEFINITION (identity + baseline voice)
        # joins the cached head. The per-turn STEER (register / modulation /
        # relationship layer / examples) is recomputed every turn by
        # PersonaTurnPlanner — keeping it above the boundary invalidated the
        # cached prefix on every turn (chat-path cache read=0). It is rendered
        # below the boundary so the bridge moves it into the per-turn message
        # tail (#100/P2a).
        lines.extend(self._render_persona_identity(context.self_memory.persona_turn_plan))
        lines.extend(self._render_persona_journal(context.self_memory.persona_journal_entries))

        # Cache boundary: identity + tool catalog + persona identity above is the
        # stable head; the per-turn blocks below (persona turn steer / memory /
        # profile / runtime+time / attachments) are moved OUT of the system prompt
        # into the message stream by the provider bridge (#100/P2a), so the system
        # head + conversation history stay a byte-stable, cacheable prefix. The
        # marker is stripped before sending so it never reaches the model.
        lines.append(SYSTEM_PROMPT_CACHE_BOUNDARY)

        # Per-turn dynamic blocks — moved to the message tail by the bridge.
        lines.extend(self._render_persona_turn_steer(context.self_memory.persona_turn_plan))
        lines.extend(self._render_memory_library(context.self_memory.retrieval_memory))
        lines.extend(self._render_profile_memory(context.profile_memory))
        lines.extend(self._render_runtime_system(context.runtime_system))
        lines.extend(self._render_active_attachments(context.runtime_system.active_attachments))

        return "\n".join(lines).strip()

    def _render_persona_identity(self, plan: PersonaTurnPlan | None) -> List[str]:
        """Render the byte-stable persona definition (Identity Core + Baseline
        Voice). This is the part that stays in the cached system head — it does
        not change across turns for a given persona."""
        if plan is None:
            return []

        lines = ["# Persona Runtime Plan"]
        lines.append(
            "[System Notice: Embody the persona defined here. The per-turn steer "
            "(register, modulation, examples) arrives with the user's turn. "
            "Do not mention the plan, register, triggers, layers, or internal state to the user.]"
        )
        lines.append("")

        lines.append("## Identity Core")
        lines.append(f"* Persona: {plan.persona_name}")
        identity_statement = str(plan.identity_core.get("identity_statement") or "").strip()
        if identity_statement:
            lines.append(identity_statement)
        loved = self._string_list(plan.identity_core.get("values_loved"))
        rejected = self._string_list(plan.identity_core.get("values_rejected"))
        biases = self._string_list(plan.identity_core.get("attention_biases"))
        if loved:
            lines.append(f"* Values Loved: {', '.join(loved)}")
        if rejected:
            lines.append(f"* Values Rejected: {', '.join(rejected)}")
        if biases:
            lines.append("* Attention Biases:")
            for bias in biases:
                lines.append(f"  - {bias}")
        lines.append("")

        lines.append("## Baseline Voice")
        sentence_style = str(plan.idiolect.get("sentence_style") or "").strip()
        if sentence_style:
            lines.append(f"* Sentence Style: {sentence_style}")
        vocab_available = self._string_list(plan.idiolect.get("vocab_available"))
        vocab_avoided = self._string_list(plan.idiolect.get("vocab_avoided"))
        quirks = self._string_list(plan.idiolect.get("structural_quirks"))
        if vocab_available:
            lines.append(f"* Available Vocabulary: {', '.join(vocab_available)}")
        if vocab_avoided:
            lines.append(f"* Avoid Vocabulary: {', '.join(vocab_avoided)}")
        if quirks:
            lines.append("* Structural Quirks:")
            for quirk in quirks:
                lines.append(f"  - {quirk}")
        lines.append("")

        return lines

    def _render_persona_turn_steer(self, plan: PersonaTurnPlan | None) -> List[str]:
        """Render the per-turn persona steer (register / clamp / triggers /
        relationship layer / modulation / examples). PersonaTurnPlanner
        recomputes these every turn, so they live below the cache boundary and
        ride in the per-turn message tail — never in the cached head (#100)."""
        if plan is None:
            return []

        lines = ["# Persona Turn Steer"]
        lines.append("")

        lines.append("## Current Register")
        lines.append(f"* Register: {plan.register}")
        lines.append(f"* Situation Strength: {plan.situation_strength}")
        lines.append(f"* Persona Intensity: {plan.persona_intensity}/3")
        if plan.register_description:
            lines.append(f"* Description: {plan.register_description}")
        if plan.register_behavior:
            lines.append(f"* Behavior: {plan.register_behavior}")
        lines.append("")

        if plan.quiet_hours:
            lines.append("## Quiet-Hour Clamp")
            for quiet_hour in plan.quiet_hours:
                condition = str(quiet_hour.get("condition") or "active").strip()
                lines.append(f"* Condition: {condition}")
                clamps = quiet_hour.get("clamps") or {}
                if isinstance(clamps, dict):
                    for key, value in clamps.items():
                        lines.append(f"  - {key}: {value}")
            lines.append("")

        if plan.active_triggers:
            lines.append("## Active Persona Triggers")
            for trigger in plan.active_triggers:
                lines.append(f"* {trigger.trigger_id} ({trigger.intensity}): {trigger.behavior_shift}")
            lines.append("")

        if plan.active_layer or plan.layer_modifiers:
            lines.append("## Relationship Layer Modifiers")
            if plan.active_layer:
                lines.append(f"* Active Layer: {plan.active_layer}")
            if plan.layer_modifiers:
                lines.extend(self._render_nested_mapping(plan.layer_modifiers, indent="* "))
            lines.append("")

        if plan.dynamic_modulations:
            lines.append("## Dynamic Modulation")
            lines.extend(self._render_nested_mapping(plan.dynamic_modulations, indent="* "))
            lines.append("")

        if plan.selected_examples:
            lines.append("## Relevant Persona Examples")
            for example in plan.selected_examples:
                lines.append(example)
                lines.append("")

        return lines

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _render_nested_mapping(self, value: Dict[str, Any], *, indent: str) -> List[str]:
        lines: List[str] = []
        for key, item in value.items():
            label = str(key).replace("_", " ").title()
            if isinstance(item, dict):
                lines.append(f"{indent}{label}:")
                for child_key, child_value in item.items():
                    lines.append(f"  - {child_key}: {child_value}")
            elif isinstance(item, list):
                lines.append(f"{indent}{label}:")
                for child_value in item:
                    lines.append(f"  - {child_value}")
            else:
                lines.append(f"{indent}{label}: {item}")
        return lines

    def _render_persona_journal(self, entries: List[Dict[str, Any]]) -> List[str]:
        """Render recent persona journal entries as contextual self-reflection."""
        if not entries:
            return []

        lines = ["# Internal Reflections"]
        lines.append(
            "[System Notice: These are your recent private journal entries. "
            "They inform your self-awareness but should not be directly quoted to the user.]"
        )
        lines.append("")

        for entry in entries:
            content = entry.get("content", "")
            ts = entry.get("timestamp", 0)
            if not content:
                continue
            dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "unknown"
            lines.append(f"**{dt}**: {content}")
            lines.append("")

        return lines

    def _render_memory_library(self, retrieval: RetrievalMemoryContext) -> List[str]:
        """Render memory library as markdown."""
        lines = ["# Memory Library"]

        lines.append("## Working Memory (L0)")
        workbench = retrieval.l0_workbench or []
        if workbench:
            for item in workbench:
                lines.append(f"* {self._format_memory_item(item)}")
        else:
            lines.append("* (empty)")
        lines.append("")

        lines.append("## Entity Cards (L2)")
        entity_cards = retrieval.l2_entity_cards or []
        if entity_cards:
            for item in entity_cards:
                lines.append(f"* {self._format_memory_item(item)}")
        else:
            lines.append("* (empty)")
        lines.append("")

        lines.append("## Reflection Memory (L3)")
        reflection = retrieval.l3_reflection_memory or []
        if reflection:
            for item in reflection:
                lines.append(f"* {self._format_memory_item(item)}")
        else:
            lines.append("* (empty)")
        lines.append("")

        lines.append("## Procedural Memory (L4)")
        procedures = retrieval.l4_procedural_memory or []
        if procedures:
            for item in procedures:
                lines.append(f"* {self._format_memory_item(item)}")
        else:
            lines.append("* (empty)")
        lines.append("")

        lines.append("## Preference Memory")
        pref = retrieval.preference_memory or {}
        if pref:
            task_pref = pref.get("task_preferences", {})
            if task_pref:
                lines.append("### Task Preferences")
                lines.append(f"* Task Category: {task_pref.get('task_category', 'unknown')}")
                lines.append(f"* Information Density: {task_pref.get('information_density', 'medium')}")
                lines.append(f"* Ambiguity Tolerance: {task_pref.get('ambiguity_tolerance', 'adaptive')}")
                lines.append(f"* Proactivity: {task_pref.get('proactivity', 'reactive')}")
            user_pref = pref.get("user_preferences", {})
            if user_pref:
                lines.append("### User Preferences")
                for key, value in user_pref.items():
                    lines.append(f"* {key}: {value}")
        else:
            lines.append("* (no preferences recorded)")
        lines.append("")

        return lines

    def _render_profile_memory(self, profile: ProfileMemoryContext) -> List[str]:
        """Render profile memory as markdown, omitting unknown/empty fields."""
        body: List[str] = []

        user_name = (profile.user_name or "").strip()
        if user_name and user_name.lower() != "unknown":
            body.append(f"* User Name: {user_name}")

        prefs = profile.user_preferences or {}
        preferred_address = self._first_profile_text(prefs.get("address.preferred"))
        stated_real_name = self._first_profile_text(prefs.get("address.real_name"))
        disallowed_addresses = self._profile_text_list(prefs.get("address.disallowed"))

        if preferred_address:
            body.append(f"* Preferred Address: {preferred_address}")
        if stated_real_name and stated_real_name != user_name:
            body.append(f"* Stated Real Name: {stated_real_name}")
        if disallowed_addresses:
            body.append(f"* Avoid Addressing As: {', '.join(disallowed_addresses)}")

        visible_prefs = {
            key: value
            for key, value in prefs.items()
            if key not in {"address.preferred", "address.real_name", "address.disallowed"}
        }
        if visible_prefs:
            body.append("* User Preferences:")
            for key, value in visible_prefs.items():
                body.append(f"  - {key}: {value}")

        emotion = profile.recent_emotion or {}
        if emotion:
            body.append("* Recent Emotion:")
            sentiment = emotion.get("sentiment_score", 0.0)
            label = emotion.get("emotion_label", "neutral")
            trust = emotion.get("trust_level", 0.5)
            trust_label = emotion.get("trust_label", "medium")
            body.append(f"  - Sentiment: {label} (score: {sentiment:.2f})")
            body.append(f"  - Trust: {trust_label} (level: {trust:.2f})")

        if not body:
            return []

        return ["# Profile Memory", *body, ""]

    @staticmethod
    def _first_profile_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
            return ""
        if isinstance(value, dict):
            return str(value.get("value") or "").strip()
        return ""

    @classmethod
    def _profile_text_list(cls, value: Any) -> List[str]:
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, dict):
            return cls._profile_text_list(value.get("value"))
        return []

    def _render_runtime_system(self, runtime: RuntimeSystemContext) -> List[str]:
        """Render runtime system as markdown."""
        lines = ["# System Information"]
        lines.append(f"* Time: {runtime.current_time_iso} ({runtime.timezone})")
        lines.append(f"* OS: {runtime.os_name} {runtime.os_version}")
        lines.append(f"* Working Directory: {runtime.cwd}")
        lines.append(f"* Agent: {runtime.agent_id} (type: {runtime.agent_type})")
        lines.append("")
        return lines

    def _render_tool_catalog(
        self,
        tools: ToolCatalogContext,
        *,
        suppress_imperatives: bool = False,
    ) -> List[str]:
        """Render tool catalog as markdown.

        ``suppress_imperatives`` controls whether the ``## Tool Usage
        Instructions`` section ("you MUST use the available tools",
        "NEVER give up and return plain text") is appended. We drop it
        for emotional / crisis registers where task-execution framing
        is the wrong register for the turn — the catalog itself stays
        visible so tools remain callable when genuinely needed.
        """
        lines = ["# Tool Information"]

        # Sort by name so an unchanged tool SET serialises identically across
        # turns even when the upstream selector reranks it (issue #97).
        selected = sorted(tools.selected_tools or [])
        lines.append("## Selected Tools")
        if selected:
            for tool in selected:
                lines.append(f"* {tool}")
        else:
            lines.append("* (none selected)")
        lines.append("")

        descriptions = sorted(
            tools.tool_descriptions or [],
            key=lambda desc: str(desc.get("name", "")),
        )
        lines.append("## Tool Catalog")
        if descriptions:
            for desc in descriptions:
                name = desc.get("name", "unknown")
                desc_text = desc.get("description", "")
                category = desc.get("category", "")
                tool_type = desc.get("type", "tool")
                lines.append(f"* **{name}** ({tool_type}): {desc_text}")
                if category:
                    lines[-1] += f" [Category: {category}]"
        else:
            lines.append("* (no tools available)")
        lines.append("")

        if selected and not suppress_imperatives:
            lines.extend([
                "## Tool Usage Instructions",
                "* You MUST use the available tools to complete the user's task.",
                "* If a tool fails, try alternative approaches using other tools or commands.",
                "* NEVER give up and return plain text suggestions - always attempt tool calls.",
                "* For bash commands: try different tools/flags if one fails (e.g., if `convert` not found, try `magick`, `sips`, or Python PIL).",
                "* Continue calling tools until the task is fully completed or all options are exhausted.",
                "",
            ])

        return lines

    def _render_active_attachments(self, attachments: List[Dict[str, Any]]) -> List[str]:
        if not attachments:
            return []

        lines = ["# Active Attachments"]
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            name = str(attachment.get("original_name") or "attachment").strip() or "attachment"
            kind = str(attachment.get("kind") or "unknown").strip() or "unknown"
            parse_status = str(attachment.get("parse_status") or "unknown").strip() or "unknown"
            lines.append(f"## {name} ({kind})")
            lines.append(f"* Parse Status: {parse_status}")

            character_count = attachment.get("character_count")
            if isinstance(character_count, int):
                lines.append(f"* Character Count: {character_count}")
            page_count = attachment.get("page_count")
            if isinstance(page_count, int):
                lines.append(f"* Page Count: {page_count}")
            if "truncated" in attachment:
                lines.append(f"* Truncated: {'yes' if bool(attachment.get('truncated')) else 'no'}")
            parse_error = str(attachment.get("parse_error") or "").strip()
            if parse_error:
                lines.append(f"* Parse Error: {parse_error}")

            attachment_text = self._load_attachment_text(attachment)
            if attachment_text:
                lines.append("### Extracted Content")
                lines.append("```text")
                lines.append(attachment_text)
                lines.append("```")
            lines.append("")
        return lines

    @staticmethod
    def _load_attachment_text(attachment: Dict[str, Any], *, max_chars: int = 24_000) -> str:
        text = ""
        text_path = str(attachment.get("derived_text_path") or "").strip()
        if text_path:
            try:
                text = Path(text_path).read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
        if not text:
            text = str(attachment.get("derived_text_excerpt") or "").strip()
        normalized = text.strip()
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[:max_chars].rstrip()}\n...[truncated]"

    def _format_memory_item(self, item: Any) -> str:
        """Format a memory item for display."""
        if isinstance(item, dict):
            title = item.get("title") or item.get("summary")
            if not title:
                content = item.get("content", "")
                title = str(content)[:50] if content else "(empty)"
            if isinstance(title, str) and len(title) > 100:
                title = title[:100] + "..."
            return str(title)
        text = str(item)
        return text[:100] if len(text) > 100 else text

    @staticmethod
    def _json_dump(payload: Any) -> str:
        import json
        return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = ["PromptContextRenderer"]