"""Fallback result building for L3 temporal summaries."""

from __future__ import annotations

from .models import L3Candidate, TemporalEvidencePack, TemporalGenerationResult
from .temporal_language import target_language_code

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
    "chat_projector": "对话",
    "chrome_history": "浏览记录",
    "chrome-history": "浏览记录",
    "git_activity": "Git 活动",
    "git-activity": "Git 活动",
    "system_media": "媒体播放",
    "system-media": "媒体播放",
    "netease_music": "网易云音乐",
    "netease-music": "网易云音乐",
    "calendar": "日历",
    "terminal_history": "终端记录",
    "terminal-history": "终端记录",
}


class TemporalFallbackBuilder:
    """Build deterministic temporal summary fallback output."""

    def build_result(
        self,
        pack: TemporalEvidencePack,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        raw_feature_lines = self.raw_plugin_summary_lines(pack)
        target_zh = target_language_code() == "zh"
        fallback_content = self.build_content(
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

    def raw_plugin_summary_lines(self, pack: TemporalEvidencePack) -> list[str]:
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

    def build_content(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
        raw_feature_lines: list[str],
    ) -> str:
        if target_language_code() != "zh":
            return str(fallback_summary).strip()

        period_label = _PERIOD_LABELS_ZH.get(str(pack.summary_category), "这段时间")
        source_labels = self.zh_source_labels(pack.source_distribution)
        if source_labels:
            parts = [f"{period_label}的记忆主要围绕{self.join_zh(source_labels)}展开"]
        else:
            parts = [f"{period_label}留下了一组可用于回顾的活动线索"]
        feature_lines = self.build_zh_feature_lines(pack)[:3]
        parts.extend(feature_lines)
        if len(parts) == 1 and _contains_cjk(str(fallback_summary)):
            parts.append(str(fallback_summary).strip())
        if len(parts) == 1 and raw_feature_lines:
            parts.append("插件提供了结构化摘要特征，可作为后续回顾的线索")
        return "。".join(part.strip().rstrip("。") for part in parts if part.strip()) + "。"

    def zh_source_labels(self, source_distribution: dict[str, object]) -> list[str]:
        labels: list[str] = []
        for key in source_distribution:
            label = _SOURCE_LABELS_ZH.get(str(key), str(key).replace("_", " "))
            if label and label not in labels:
                labels.append(label)
        return labels[:4]

    def join_zh(self, values: list[str]) -> str:
        cleaned = [item.strip() for item in values if item.strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return "和".join(cleaned)
        return "、".join(cleaned[:-1]) + f"和{cleaned[-1]}"

    def build_zh_feature_lines(self, pack: TemporalEvidencePack) -> list[str]:
        lines: list[str] = []
        for feature in pack.plugin_summary_features.values():
            if not isinstance(feature, dict):
                continue
            focus_domain = str(feature.get("focus_domain") or "").strip()
            if focus_domain:
                lines.append(f"浏览活动主要集中在 {focus_domain}")
            top_domains = feature.get("top_domains")
            if isinstance(top_domains, list):
                domains = [
                    str(item.get("domain") or "").strip()
                    for item in top_domains
                    if isinstance(item, dict)
                ]
                domains = [domain for domain in domains if domain]
                if domains:
                    other_domains = [domain for domain in domains if domain != focus_domain]
                    domain_line = other_domains[:4] if other_domains else domains[:4]
                    lines.append(f"高频访问还包括 {'、'.join(domain_line)}")
        return lines


def _contains_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


__all__ = ["TemporalFallbackBuilder"]
