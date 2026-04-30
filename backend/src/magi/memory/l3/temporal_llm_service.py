"""Rule-side helpers for temporal L3 LLM summarization."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from ...config.loader import get_user_preference
from ...llm import LLMProviderBridge, LLMScenario, ScenarioLLMPool
from magi_plugin_sdk.i18n import get_current_language
from .models import L3Candidate, TemporalEvidencePack, TemporalGenerationResult, TemporalSummaryLLMOutput
from .temporal_evidence import TemporalEvidencePackMixin
from .temporal_output import TemporalOutputParsingMixin
from .temporal_prompts import TEMPORAL_SUMMARY_OUTPUT_SCHEMA, TEMPORAL_SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]{3,}")
_LEGACY_FLAT_TIMEOUT_SECONDS = 3.0
_PERIOD_TIMEOUT_SECONDS = {
    "hour": 180.0,
    "day": 300.0,
    "week": 600.0,
    "month": 600.0,
    "quarter": 600.0,
    "year": 600.0,
}
_PERIOD_DISABLE_THINKING = {
    "hour": True,
    "day": False,
    "week": False,
    "month": False,
    "quarter": False,
    "year": False,
}
_PERIOD_FOCUS_INSTRUCTIONS = {
    "hour": (
        "- Hour focus: capture the local sequence, immediate context, and short-lived shifts inside this hour.\n"
        "- Avoid turning one hour of activity into a durable preference or long-term trend."
    ),
    "day": (
        "- Day focus: identify the main blocks of the day, attention shifts, explicit decisions, and repeated constraints.\n"
        "- Separate meaningful patterns from ordinary single-event noise."
    ),
    "week": (
        "- Week focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the week.\n"
        "- Prefer pattern-level interpretation over listing events one by one."
    ),
    "month": (
        "- Month focus: synthesize cross-week themes, stage changes, sustained interests, project progress, and unusually frequent activities across the month.\n"
        "- Prefer a timeline-oriented month recap over listing weekly summaries one by one."
    ),
    "quarter": (
        "- Long-window focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the window.\n"
        "- Prefer pattern-level interpretation over listing events one by one."
    ),
    "year": (
        "- Long-window focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the window.\n"
        "- Prefer pattern-level interpretation over listing events one by one."
    ),
}
_PERIOD_LABELS_ZH = {
    "hour": "这一小时",
    "day": "这一天",
    "week": "这一周",
    "month": "这个月",
    "quarter": "这个季度",
    "year": "这一年",
}
_SOURCE_LABELS_ZH = {
    "chat": "对话",
    "chrome_history": "浏览记录",
    "git_activity": "Git 活动",
    "system_media": "媒体播放",
    "netease_music": "网易云音乐",
    "calendar": "日历",
    "terminal_history": "终端记录",
}


def _target_language_code() -> str:
    preferred = get_user_preference("language", None)
    language = str(preferred or get_current_language() or "en").lower()
    return "zh" if language.startswith("zh") else "en"


def _target_language_label() -> str:
    return "Simplified Chinese (zh-CN)" if _target_language_code() == "zh" else "English"


def _target_language_instruction() -> str:
    target = _target_language_label()
    return (
        f"- The target language is {target}.\n"
        f"- Write every user-facing generated field in {target}: content, key_topics, "
        "sentiment_summary natural-language strings, and change_and_pattern strings.\n"
        "- This language rule is mandatory even when evidence, rule_hints, or plugin_summary_features are written in another language.\n"
        "- Preserve event ids, entity ids, URLs, file paths, source names, product names, song titles, and quoted user text as evidence presents them."
    )


def _render_temporal_summary_system_prompt() -> str:
    return (
        TEMPORAL_SUMMARY_SYSTEM_PROMPT
        + "\nLanguage Rules:\n"
        + f"- Target language: {_target_language_label()}.\n"
        + "- All user-facing JSON string values MUST use the target language.\n"
        + "- Evidence text may be in another language; summarize it in the target language unless preserving a name, URL, ID, path, title, or direct quote.\n"
    )


class TemporalSummaryLLMService(TemporalEvidencePackMixin, TemporalOutputParsingMixin):
    """Build evidence packs, call the LLM, and parse temporal summaries."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 3.0,
        min_event_count_for_llm: int = 2,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        normalized_timeout = float(llm_timeout_seconds)
        self._llm_timeout_seconds = (
            None if normalized_timeout == _LEGACY_FLAT_TIMEOUT_SECONDS else normalized_timeout
        )
        self._min_event_count_for_llm = max(1, int(min_event_count_for_llm))
        self._scenario_llm_pool = scenario_llm_pool

    async def generate_temporal_candidate(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        """Try the model path and fall back to a rule summary on failure."""
        fallback = self._build_fallback_result(pack, fallback_summary)
        if not self._enabled:
            return fallback
        if pack.source_event_count < self._min_event_count_for_llm:
            return fallback
        timeout_seconds = self._timeout_seconds_for_pack(pack)
        disable_thinking = self._disable_thinking_for_pack(pack)
        try:
            payload = await asyncio.wait_for(
                self._call_temporal_model(
                    pack,
                    timeout_seconds=timeout_seconds,
                    disable_thinking=disable_thinking,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "L3 temporal LLM call timed out",
                extra={
                    "summary_category": pack.summary_category,
                    "event_count": pack.source_event_count,
                    "timeout_seconds": timeout_seconds,
                    "thinking_enabled": not disable_thinking,
                },
            )
            return fallback
        except Exception:
            return fallback
        if not isinstance(payload, dict):
            return fallback
        try:
            candidate, summary_overrides = self.parse_llm_output(payload, pack=pack)
        except Exception:
            return fallback
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    async def _call_temporal_model(
        self,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> dict[str, Any] | None:
        """Call the configured LLM adapter for temporal summary generation."""
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        prompt = self._render_temporal_summary_prompt(pack)
        system_prompt = _render_temporal_summary_system_prompt()
        resolved_timeout_seconds = timeout_seconds or self._timeout_seconds_for_pack(pack)
        resolved_disable_thinking = (
            disable_thinking if disable_thinking is not None else self._disable_thinking_for_pack(pack)
        )
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_temporal_summary",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "summary_category": pack.summary_category,
            "timeout_seconds": resolved_timeout_seconds,
            "thinking_enabled": not resolved_disable_thinking,
        }
        logger.info("L3 temporal LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=resolved_disable_thinking,
                timeout_seconds=resolved_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_temporal_summary",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
            )
        except Exception as exc:
            logger.warning("L3 temporal LLM call failed", extra={**log_context, "error": str(exc)})
            raise

        raw = response.content
        logger.info(
            "L3 temporal LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw or ""),
            },
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("L3 temporal LLM returned invalid JSON", extra=log_context)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _timeout_seconds_for_pack(self, pack: TemporalEvidencePack) -> float:
        if self._llm_timeout_seconds is not None:
            return self._llm_timeout_seconds
        return _PERIOD_TIMEOUT_SECONDS.get(str(pack.summary_category), _PERIOD_TIMEOUT_SECONDS["week"])

    def _disable_thinking_for_pack(self, pack: TemporalEvidencePack) -> bool:
        return _PERIOD_DISABLE_THINKING.get(str(pack.summary_category), False)

    def _build_fallback_result(
        self,
        pack: TemporalEvidencePack,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        raw_feature_lines = self._raw_plugin_summary_lines(pack)
        target_zh = _target_language_code() == "zh"
        fallback_content = self._build_fallback_content(
            pack,
            fallback_summary=fallback_summary,
            raw_feature_lines=raw_feature_lines,
        )
        candidate = L3Candidate(
            summary_type="temporal",
            summary_category=pack.summary_category,
            content=fallback_content,
            source_event_ids=list(pack.source_event_ids),
        )
        summary_overrides: dict[str, object] = {
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": dict(pack.event_type_distribution),
        }
        if raw_feature_lines:
            summary_overrides["plugin_summary_features"] = dict(pack.plugin_summary_features)
        if raw_feature_lines and not target_zh:
            stitched = [fallback_content, *raw_feature_lines]
            candidate.content = "\n".join(part for part in stitched if part).strip()
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=True,
        )

    def _raw_plugin_summary_lines(self, pack: TemporalEvidencePack) -> list[str]:
        feature_lines: list[str] = []
        for feature in pack.plugin_summary_features.values():
            if not isinstance(feature, dict):
                continue
            raw_lines = feature.get("summary_lines")
            if not isinstance(raw_lines, list):
                continue
            for item in raw_lines:
                line = str(item).strip()
                if line and line not in feature_lines:
                    feature_lines.append(line)
        return feature_lines

    def _build_fallback_content(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
        raw_feature_lines: list[str],
    ) -> str:
        if _target_language_code() != "zh":
            return str(fallback_summary).strip()

        period_label = _PERIOD_LABELS_ZH.get(str(pack.summary_category), "这段时间")
        source_labels = self._zh_source_labels(pack.source_distribution)
        if source_labels:
            parts = [f"{period_label}的记忆主要围绕{self._join_zh(source_labels)}展开"]
        else:
            parts = [f"{period_label}留下了一组可用于回顾的活动线索"]
        feature_lines = self._build_zh_feature_lines(pack)[:3]
        parts.extend(feature_lines)
        if len(parts) == 1 and _CJK_PATTERN.search(str(fallback_summary)):
            parts.append(str(fallback_summary).strip())
        if len(parts) == 1 and raw_feature_lines:
            parts.append("插件提供了结构化摘要特征，可作为后续回顾的线索")
        return "。".join(part.strip().rstrip("。") for part in parts if part.strip()) + "。"

    def _zh_source_labels(self, source_distribution: dict[str, object]) -> list[str]:
        labels: list[str] = []
        for key in source_distribution:
            label = _SOURCE_LABELS_ZH.get(str(key), str(key).replace("_", " "))
            if label and label not in labels:
                labels.append(label)
        return labels[:4]

    def _join_zh(self, values: list[str]) -> str:
        cleaned = [item.strip() for item in values if item.strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return "和".join(cleaned)
        return "、".join(cleaned[:-1]) + f"和{cleaned[-1]}"

    def _build_zh_feature_lines(self, pack: TemporalEvidencePack) -> list[str]:
        lines: list[str] = []
        for feature in pack.plugin_summary_features.values():
            if not isinstance(feature, dict):
                continue
            focus_domain = str(feature.get("focus_domain") or "").strip()
            if focus_domain:
                lines.append(f"浏览活动主要集中在 {focus_domain}")
            top_domains = feature.get("top_domains")
            if isinstance(top_domains, list):
                domains = [str(item.get("domain") or "").strip() for item in top_domains if isinstance(item, dict)]
                domains = [domain for domain in domains if domain]
                if domains:
                    other_domains = [domain for domain in domains if domain != focus_domain]
                    domain_line = other_domains[:4] if other_domains else domains[:4]
                    lines.append(f"高频访问还包括 {'、'.join(domain_line)}")
        return lines

    def _validate_target_language(self, output: TemporalSummaryLLMOutput) -> None:
        if _target_language_code() != "zh":
            return
        for text in self._user_facing_strings(output):
            if self._looks_like_non_zh_user_text(text):
                raise ValueError("Temporal LLM output does not match target language zh-CN")

    def _user_facing_strings(self, output: TemporalSummaryLLMOutput) -> list[str]:
        strings = [output.content, *output.key_topics]
        if isinstance(output.sentiment_summary, dict):
            strings.extend(str(value) for value in output.sentiment_summary.values() if isinstance(value, str))
        if isinstance(output.change_and_pattern, dict):
            for value in output.change_and_pattern.values():
                if isinstance(value, list):
                    strings.extend(str(item) for item in value if isinstance(item, str))
                elif isinstance(value, str):
                    strings.append(value)
        return [item.strip() for item in strings if item.strip()]

    def _looks_like_non_zh_user_text(self, text: str) -> bool:
        if _CJK_PATTERN.search(text):
            return False
        return bool(_LATIN_WORD_PATTERN.search(text))

    def _render_temporal_summary_prompt(self, pack: TemporalEvidencePack) -> str:
        payload = {
            "summary_type": "temporal",
            "summary_category": pack.summary_category,
            "period_start": pack.period_start,
            "period_end": pack.period_end,
            "window_event_count": pack.window_event_count if pack.window_event_count is not None else pack.source_event_count,
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
                }
                for item in pack.events
            ],
        }
        schema = json.dumps(TEMPORAL_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        evidence = json.dumps(payload, ensure_ascii=False, indent=2)
        period_focus = self._period_focus_instruction(pack)
        return (
            "Task:\n"
            "Write a temporal summary for the provided memory window.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "When plugin_summary_features are present, use them to surface source-specific behavior patterns such as concentration, revisits, and session structure.\n"
            "Use source_distribution, window_event_count, and omitted_event_count to understand coverage and avoid treating representative events as exhaustive.\n"
            "Prioritize explicit changes, recurring constraints, and high-importance events.\n\n"
            "Use previous_period_summaries and child_period_summaries only for comparison and timeline continuity; the current evidence pack remains the source of truth.\n"
            "Do not promote old summary content into a current-window fact unless current evidence also supports it.\n"
            "Do not lead with raw event counts or internal event type names; mention counts only when they change the interpretation.\n\n"
            "Period Focus:\n"
            f"{period_focus}\n\n"
            "Output Requirements:\n"
            "- Return one JSON object only.\n"
            "- Keep content concise and evidence-grounded.\n"
            f"{_target_language_instruction()}\n"
            "- Use empty lists or nulls when a field has no support.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n\n"
            "Evidence Pack:\n"
            f"{evidence}\n"
        )

    def _period_focus_instruction(self, pack: TemporalEvidencePack) -> str:
        return _PERIOD_FOCUS_INSTRUCTIONS.get(
            str(pack.summary_category),
            _PERIOD_FOCUS_INSTRUCTIONS["week"],
        )

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.MEMORY_SUMMARIZER)
        except Exception as exc:
            logger.debug("L3 temporal LLM adapter unavailable: %s", exc)
            return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)


__all__ = [
    "TEMPORAL_SUMMARY_OUTPUT_SCHEMA",
    "TEMPORAL_SUMMARY_SYSTEM_PROMPT",
    "TemporalSummaryLLMService",
]
