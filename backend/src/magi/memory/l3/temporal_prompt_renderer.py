"""Prompt rendering for L3 temporal summary generation."""

from __future__ import annotations

import json

from .models import TemporalEvidencePack
from .temporal_language import target_language_instruction
from .temporal_policy import TemporalSummaryPolicy
from .temporal_prompts import TEMPORAL_SUMMARY_OUTPUT_SCHEMA


class TemporalPromptRenderer:
    """Render temporal summary prompts from evidence and period policy."""

    def __init__(self, *, policy: TemporalSummaryPolicy | None = None) -> None:
        self._policy = policy or TemporalSummaryPolicy()

    def prompt_payload(self, pack: TemporalEvidencePack) -> dict[str, object]:
        return {
            "summary_type": "temporal",
            "summary_category": pack.summary_category,
            "period_start": pack.period_start,
            "period_end": pack.period_end,
            "window_event_count": (
                pack.window_event_count
                if pack.window_event_count is not None
                else pack.source_event_count
            ),
            "source_event_count": pack.source_event_count,
            "omitted_event_count": pack.omitted_event_count,
            "source_event_ids": pack.source_event_ids,
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": pack.event_type_distribution,
            "rule_hints": pack.rule_hints,
            "plugin_summary_features": pack.plugin_summary_features,
            "source_distribution": pack.source_distribution,
            "selection_policy": pack.selection_policy,
            "previous_period_summaries": pack.previous_period_summaries,
            "child_period_summaries": pack.child_period_summaries,
            "events": [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "timestamp": item.timestamp,
                    "memory_domain": item.memory_domain,
                    "importance_score": item.importance_score,
                    "content": item.content,
                    "interpretation_context": item.interpretation_context,
                }
                for item in pack.events
            ],
        }

    def render_context_prompt(self, pack: TemporalEvidencePack) -> str:
        payload = self.prompt_payload(pack)
        evidence = json.dumps(payload, ensure_ascii=False, indent=2)
        period_focus = self._policy.focus_instruction(pack.summary_category)
        period_structure = self._policy.structure_instruction(pack.summary_category)
        return (
            "Shared Context:\n"
            "You are working on one temporal memory summary for the provided memory window.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "An event's interpretation_context only explains how to read its content. The product-authored question is not evidence and must never be presented as something the user said, believed, or experienced.\n"
            "When plugin_summary_features are present, use them to surface source-specific behavior patterns such as concentration, revisits, and session structure.\n"
            "Use source_distribution, window_event_count, and omitted_event_count to understand coverage and avoid treating representative events as exhaustive.\n"
            "Prioritize explicit changes, recurring constraints, and high-importance events.\n\n"
            "Use previous_period_summaries as an ordered comparison series for trend_shifts and vs-previous-period sections; the current evidence pack remains the source of truth.\n"
            "When child_period_summaries are present (week/month/quarter/year), treat them as the primary skeleton: synthesize from child headlines, decisions, and open threads, and fall back to raw events only to fill gaps.\n"
            "Do not promote old summary content into a current-window fact unless current evidence also supports it.\n"
            "Do not lead with raw event counts or internal event type names; mention counts only when they change the interpretation.\n\n"
            "Period Focus:\n"
            f"{period_focus}\n\n"
            "Structure Contract:\n"
            f"{period_structure}\n\n"
            "Language Rules:\n"
            f"{target_language_instruction()}\n\n"
            "Evidence Pack:\n"
            f"{evidence}\n"
        )

    def render_prose_prompt(self, pack: TemporalEvidencePack) -> str:
        return (
            self.render_context_prompt(pack) + "\nGeneration Task / 生成用户可读正文:\n"
            "- Write only the user-facing summary body.\n"
            "- Do not return JSON.\n"
            "- Keep the tone concrete, neutral, and compact; avoid literary prose.\n"
            "- Use Markdown only when section headings or bullets help clarity.\n"
            "- Preserve concrete names that improve future recall, but do not dump raw event lists.\n"
        )

    def render_structure_prompt(
        self,
        pack: TemporalEvidencePack,
        *,
        prose_content: str,
    ) -> str:
        schema = json.dumps(TEMPORAL_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            self.render_context_prompt(pack) + "\nAccepted User-Facing Summary:\n"
            f"{prose_content.strip()}\n\n"
            "Extraction Task / 提取结构化字段:\n"
            "- Extract optional structured fields from the same evidence and accepted summary.\n"
            "- Do not rewrite the accepted summary.\n"
            "- Write `essence_prose` as a short card preview: 1-2 natural sentences, grounded in the accepted summary and evidence, with no section headings.\n"
            "- Return one JSON object only.\n"
            "- `content` is optional here; when present it must exactly match the accepted summary.\n"
            "- Use empty lists or nulls when a field has no support; never fabricate metrics.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n"
        )

    def render_summary_prompt(self, pack: TemporalEvidencePack) -> str:
        schema = json.dumps(TEMPORAL_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            "Task:\n"
            "Write a temporal summary for the provided memory window.\n"
            f"{self.render_context_prompt(pack)}\n"
            "Output Requirements:\n"
            "- Return one JSON object only.\n"
            "- The `content` field must be user-facing Markdown (no top-level `#`). Prefer a short natural recap plus only the sections or bullets that help clarity; omit unsupported sections entirely.\n"
            "- The `essence_prose` field must be a short card preview: 1-2 natural sentences with no headings or bullets.\n"
            "- `change_and_pattern.headline` is REQUIRED and must mirror the headline section's one-line summary in `content`.\n"
            "- Keep `content` and `change_and_pattern` consistent: every concrete anchor in content should also appear in the appropriate structured array.\n"
            "- Preserve concrete names and short phrases that improve future retrieval.\n"
            f"{target_language_instruction()}\n"
            "- Use empty lists or nulls when a field has no support; never fabricate metrics.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n"
        )


__all__ = ["TemporalPromptRenderer"]
