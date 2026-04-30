"""Plugin-owned projection hooks for summaries and recall artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
from typing import Any

from .base import Plugin
from .contracts import SummaryProfileSpec, TemporalSummaryFeatureBudget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergedSummaryProfile:
    """Summary profile after merging plugins that share a ``summary_category``."""

    summary_category: str
    source_types: tuple[str, ...]
    windows: tuple[str, ...]
    settle_window_seconds: float
    min_events: int
    intent_verbs: tuple[str, ...]
    contributing_profile_ids: tuple[str, ...]
    prompt_hints: dict[str, Any]


class PluginProjectionMixin:
    """Collect plugin-provided temporal and recall projections."""

    def iter_loaded_plugins(self) -> list[Plugin]:
        raise NotImplementedError

    def build_temporal_summary_features(
        self,
        *,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
        source_filter: list[str] | None = None,
        feature_budgets: dict[str, TemporalSummaryFeatureBudget | dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Collect plugin-provided temporal summary features for the current event window."""

        features_by_source: dict[str, Any] = {}
        events_by_source: dict[str, list[dict[str, Any]]] = {}
        normalized_filter = {str(s).strip() for s in source_filter or [] if str(s).strip()}
        for event in events:
            source_type = str(event.get("source") or "").strip()
            if not source_type:
                continue
            if normalized_filter and source_type not in normalized_filter:
                continue
            events_by_source.setdefault(source_type, []).append(event)

        if not events_by_source:
            return features_by_source

        for plugin in self.iter_loaded_plugins():
            for source_type, source_events in events_by_source.items():
                if source_type in features_by_source:
                    continue
                try:
                    kwargs: dict[str, Any] = {
                        "source_type": source_type,
                        "events": source_events,
                        "summary_category": summary_category,
                        "period_start": period_start,
                        "period_end": period_end,
                    }
                    if self._plugin_accepts_temporal_budget(plugin):
                        budget = (feature_budgets or {}).get(source_type)
                        if isinstance(budget, dict):
                            budget = TemporalSummaryFeatureBudget(**budget)
                        if budget is not None:
                            kwargs["budget"] = budget
                    features = plugin.build_temporal_summary_features(**kwargs)
                except Exception as exc:
                    logger.warning(
                        "Plugin temporal summary feature builder failed",
                        extra={"plugin_id": plugin.plugin_id, "source_type": source_type, "error": str(exc)},
                    )
                    continue
                if features:
                    dumper = getattr(features, "model_dump", None)
                    features_by_source[source_type] = dumper() if callable(dumper) else features
        return features_by_source

    @staticmethod
    def _plugin_accepts_temporal_budget(plugin: Plugin) -> bool:
        """Return whether a plugin hook can accept the optional budget keyword."""
        try:
            signature = inspect.signature(plugin.build_temporal_summary_features)
        except (TypeError, ValueError):
            return False
        return any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD or name == "budget"
            for name, parameter in signature.parameters.items()
        )

    def iter_summary_profiles(self) -> list[SummaryProfileSpec]:
        """Aggregate ``SummaryProfileSpec`` entries from all loaded plugins."""

        profiles: list[SummaryProfileSpec] = []
        seen: set[str] = set()
        for plugin in self.iter_loaded_plugins():
            getter = getattr(plugin, "get_summary_profiles", None)
            if not callable(getter):
                continue
            try:
                items = getter() or []
            except Exception as exc:
                logger.warning(
                    "Plugin get_summary_profiles failed",
                    extra={"plugin_id": plugin.plugin_id, "error": str(exc)},
                )
                continue
            for spec in items:
                if not isinstance(spec, SummaryProfileSpec):
                    continue
                if spec.profile_id in seen:
                    continue
                seen.add(spec.profile_id)
                profiles.append(spec)
        return profiles

    def iter_merged_summary_profiles(self) -> list[MergedSummaryProfile]:
        """Aggregate per-plugin profiles into one entry per ``summary_category``."""

        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for spec in self.iter_summary_profiles():
            entry = merged.get(spec.summary_category)
            if entry is None:
                entry = {
                    "source_types": list(spec.source_types or []),
                    "windows": list(spec.windows or []),
                    "settle_window_seconds": float(spec.settle_window_seconds),
                    "min_events": int(spec.min_events),
                    "intent_verbs": list(spec.intent_verbs or []),
                    "contributing_profile_ids": [spec.profile_id],
                    "prompt_hints": dict(spec.prompt_hints or {}),
                }
                merged[spec.summary_category] = entry
                order.append(spec.summary_category)
                continue
            for source_type in spec.source_types or []:
                if source_type not in entry["source_types"]:
                    entry["source_types"].append(source_type)
            for window in spec.windows or []:
                if window not in entry["windows"]:
                    entry["windows"].append(window)
            for verb in spec.intent_verbs or []:
                if verb not in entry["intent_verbs"]:
                    entry["intent_verbs"].append(verb)
            entry["min_events"] = max(entry["min_events"], int(spec.min_events))
            entry["settle_window_seconds"] = min(
                entry["settle_window_seconds"], float(spec.settle_window_seconds),
            )
            entry["contributing_profile_ids"].append(spec.profile_id)
            for key, value in (spec.prompt_hints or {}).items():
                entry["prompt_hints"].setdefault(key, value)

        return [
            MergedSummaryProfile(
                summary_category=category,
                source_types=tuple(merged[category]["source_types"]),
                windows=tuple(merged[category]["windows"] or ["day"]),
                settle_window_seconds=merged[category]["settle_window_seconds"],
                min_events=merged[category]["min_events"],
                intent_verbs=tuple(merged[category]["intent_verbs"]),
                contributing_profile_ids=tuple(merged[category]["contributing_profile_ids"]),
                prompt_hints=dict(merged[category]["prompt_hints"]),
            )
            for category in order
        ]

    def build_recall_artifacts(
        self,
        *,
        events: list[dict[str, Any]],
        query: str,
        query_mode: str | None,
    ) -> dict[str, Any]:
        """Collect plugin-provided recall artifacts for the current query window."""

        artifacts: dict[str, Any] = {"entity_refs": [], "asset_refs": []}
        events_by_source: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            source_type = str(event.get("source") or "").strip()
            metadata = event.get("metadata_json") if isinstance(event.get("metadata_json"), dict) else {}
            timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
            source_type = str(timeline.get("source_type") or source_type).strip()
            if not source_type:
                continue
            events_by_source.setdefault(source_type, []).append(event)

        if not events_by_source:
            return artifacts

        for plugin in self.iter_loaded_plugins():
            builder = getattr(plugin, "build_recall_artifacts", None)
            if not callable(builder):
                continue
            for source_type, source_events in events_by_source.items():
                try:
                    features = builder(
                        source_type=source_type,
                        events=source_events,
                        query=query,
                        query_mode=query_mode,
                    )
                except Exception as exc:
                    logger.warning(
                        "Plugin recall artifact builder failed",
                        extra={"plugin_id": plugin.plugin_id, "source_type": source_type, "error": str(exc)},
                    )
                    continue
                if not isinstance(features, dict):
                    continue
                for key in ("entity_refs", "asset_refs"):
                    value = features.get(key)
                    if isinstance(value, list):
                        artifacts[key].extend(item for item in value if isinstance(item, dict))
        return artifacts