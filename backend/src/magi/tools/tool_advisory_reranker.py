"""Shared reranking helpers for L4 tool advisory signals."""

from __future__ import annotations

from typing import Any


class ToolAdvisoryReranker:
    """Apply advisory signals to tool candidate ordering."""

    def build_index(self, advisories: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for item in advisories or []:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name") or item.get("name") or "").strip()
            if not tool_name:
                continue
            indexed[tool_name] = dict(item)
        return indexed

    def rerank_tool_names(
        self,
        *,
        tool_names: list[str],
        advisories: list[dict[str, Any]] | None,
    ) -> list[str]:
        if not tool_names:
            return []
        advisory_index = self.build_index(advisories)
        ranked: list[tuple[float, int, str]] = []
        for original_index, tool_name in enumerate(tool_names):
            advisory = advisory_index.get(tool_name)
            if advisory is not None and advisory.get("available") is False:
                continue
            priority = self._compute_l4_score_bonus(advisory) if advisory is not None else 0.0
            ranked.append((priority, original_index, tool_name))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [name for _, _, name in ranked]

    def rerank_recommendations(
        self,
        *,
        recommendations: list[dict[str, Any]],
        advisories: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not recommendations:
            return []
        advisory_index = self.build_index(advisories)
        ranked: list[dict[str, Any]] = []
        for recommendation in recommendations:
            name = str(recommendation.get("tool") or recommendation.get("name") or "").strip()
            advisory = advisory_index.get(name)
            if advisory is not None and advisory.get("available") is False:
                continue

            updated = dict(recommendation)
            if advisory is None:
                ranked.append(updated)
                continue

            updated["score"] = round(
                float(updated.get("score") or 0.0) + self._compute_l4_score_bonus(advisory),
                4,
            )
            updated["reason"] = self._merge_reason(
                base_reason=str(updated.get("reason") or "").strip(),
                advisory=advisory,
            )
            updated["l4_advisory"] = self._compact_advisory(advisory)
            ranked.append(updated)

        ranked.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return ranked

    def compress_for_prompt(
        self,
        *,
        advisories: list[dict[str, Any]] | None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        advisory_index = self.build_index(advisories)
        ranked = sorted(
            advisory_index.values(),
            key=self._prompt_priority,
            reverse=True,
        )
        return [
            {"tool_name": str(item.get("tool_name") or ""), **self._compact_advisory(item)}
            for item in ranked[:limit]
        ]

    @staticmethod
    def _compute_l4_score_bonus(advisory: dict[str, Any]) -> float:
        bonus = 0.0
        breaker_state = str(advisory.get("breaker_state") or "").strip().lower()
        if breaker_state == "half_open":
            bonus -= 0.2

        try:
            context_fit_raw = advisory.get("context_fit")
            context_fit = None if context_fit_raw is None else float(context_fit_raw)
        except (TypeError, ValueError):
            context_fit = None
        if context_fit is not None:
            context_fit = max(0.0, min(context_fit, 1.0))
            bonus += context_fit * 0.45

        try:
            success_rate = float(advisory.get("success_rate") or 0.0)
        except (TypeError, ValueError):
            success_rate = 0.0
        try:
            total_attempts = int(advisory.get("total_attempts") or 0)
        except (TypeError, ValueError):
            total_attempts = 0
        if total_attempts >= 3:
            bonus += (success_rate - 0.5) * 0.35
            if success_rate < 0.5:
                bonus -= 0.1
        elif total_attempts > 0 and success_rate >= 0.8:
            bonus += 0.05

        if str(advisory.get("strategy_hint") or "").strip():
            bonus += 0.08

        return bonus

    def _prompt_priority(self, advisory: dict[str, Any]) -> float:
        priority = self._compute_l4_score_bonus(advisory)
        if advisory.get("available") is False:
            priority += 0.8
        if str(advisory.get("risk_note") or "").strip():
            priority += 0.2
        return priority

    @staticmethod
    def _merge_reason(*, base_reason: str, advisory: dict[str, Any]) -> str:
        notes: list[str] = []

        try:
            context_fit_raw = advisory.get("context_fit")
            context_fit = None if context_fit_raw is None else float(context_fit_raw)
        except (TypeError, ValueError):
            context_fit = None
        if context_fit is not None:
            if context_fit >= 0.75:
                notes.append("strong historical fit for similar contexts")
            elif context_fit >= 0.4:
                notes.append("historically used in similar contexts")

        try:
            success_rate = float(advisory.get("success_rate") or 0.0)
        except (TypeError, ValueError):
            success_rate = 0.0
        try:
            total_attempts = int(advisory.get("total_attempts") or 0)
        except (TypeError, ValueError):
            total_attempts = 0
        if total_attempts >= 3 and success_rate >= 0.8:
            notes.append(f"strong historical success ({success_rate:.0%} over {total_attempts} runs)")

        strategy_hint = str(advisory.get("strategy_hint") or "").strip()
        if strategy_hint:
            notes.append(f"tip: {strategy_hint}")

        if not notes:
            return base_reason
        if not base_reason:
            return "; ".join(notes)
        return f"{base_reason}; {'; '.join(notes)}"

    @staticmethod
    def _compact_advisory(advisory: dict[str, Any]) -> dict[str, Any]:
        return {
            "available": bool(advisory.get("available", True)),
            "breaker_state": str(advisory.get("breaker_state") or "closed"),
            "success_rate": advisory.get("success_rate"),
            "total_attempts": advisory.get("total_attempts"),
            "context_fit": advisory.get("context_fit"),
            "strategy_hint": advisory.get("strategy_hint"),
            "risk_note": advisory.get("risk_note"),
        }


__all__ = ["ToolAdvisoryReranker"]
