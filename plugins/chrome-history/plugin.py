"""Chrome history timeline plugin."""
from __future__ import annotations

from collections import Counter
from typing import Any

from magi.plugins import ActivationFlowSpec, ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .chrome_reader import _default_chrome_root
from .sensor import ChromeHistoryTimelineSensor


DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_mode": "manual",
    "sync_interval_minutes": 30,
    "default_retention_mode": "analyze_only",
    "storage_mode": "managed",
    "profile": "Default",
    "lookback_hours": 24,
    "max_items_per_sync": 200,
    "fetch_page_content": False,
    "initial_sync_policy": "lookback_days",
    "initial_sync_lookback_days": 7,
    "initial_sync_configured": False,
}
_SESSION_GAP_SECONDS = 30 * 60


def _activation_flow(prefix: str) -> ActivationFlowSpec:
    return ActivationFlowSpec(
        title="Enable Chrome History",
        description=(
            "Chrome history is sensitive local data. Choose how the first sync should seed the timeline before "
            "this source starts running."
        ),
        confirm_label="Enable source",
        cancel_label="Not now",
        enabled_key=f"{prefix}.enabled",
        configured_key=f"{prefix}.initial_sync_configured",
        fields=[
            ExtensionFieldSpec(
                key=f"{prefix}.initial_sync_policy",
                type="select",
                label="First Sync Scope",
                description="Decide how much history should be imported when this source is enabled for the first time.",
                default="lookback_days",
                options=[
                    ExtensionFieldOption(label="Sync full history", value="full"),
                    ExtensionFieldOption(label="Sync recent days", value="lookback_days"),
                    ExtensionFieldOption(label="Only new records from now on", value="from_now"),
                ],
                section="activation",
                surface="timeline",
                order=10,
            ),
            ExtensionFieldSpec(
                key=f"{prefix}.initial_sync_lookback_days",
                type="number",
                label="Recent Days",
                description="Used when the first-sync scope is set to recent days.",
                default=7,
                section="activation",
                surface="timeline",
                order=20,
                depends_on_key=f"{prefix}.initial_sync_policy",
                depends_on_values=["lookback_days"],
            ),
        ],
    )


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enabled",
            description="Whether Chrome history sync is active.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.profile",
            type="input",
            label="Profile",
            description="Chrome profile directory to read, such as Default or Profile 1.",
            default="Default",
            section="general",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_mode",
            type="select",
            label="Sync Mode",
            description="How Chrome history should be synchronized.",
            default="manual",
            required=True,
            options=[
                ExtensionFieldOption(label="Manual", value="manual"),
                ExtensionFieldOption(label="Interval", value="interval"),
            ],
            section="general",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="number",
            label="Sync Interval (minutes)",
            description="Polling interval used for interval-based sync.",
            default=30,
            section="general",
            surface="timeline",
            order=40,
            depends_on_key=f"{prefix}.sync_mode",
            depends_on_values=["interval"],
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.lookback_hours",
            type="number",
            label="Lookback Hours",
            description="Initial lookback window used before a cursor exists.",
            default=24,
            section="general",
            surface="timeline",
            order=50,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.max_items_per_sync",
            type="number",
            label="Max Items Per Sync",
            description="Maximum number of history records to ingest per run.",
            default=200,
            section="general",
            surface="timeline",
            order=60,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.fetch_page_content",
            type="switch",
            label="Fetch Page Content",
            description="Reserved for future page-content capture. Disabled in v1.",
            default=False,
            section="analysis",
            surface="timeline",
            order=70,
        ),
    ]


class ChromeHistoryPlugin(Plugin):
    """Registers the Chrome history timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("chrome_history", {}))
        sensor = ChromeHistoryTimelineSensor(
            retention_mode=str(settings.get("default_retention_mode") or DEFAULT_SETTINGS["default_retention_mode"]),
            source_path=str(settings.get("source_path") or _default_chrome_root()),
            fetch_page_content=bool(settings.get("fetch_page_content", DEFAULT_SETTINGS["fetch_page_content"])),
            profile=str(settings.get("profile") or DEFAULT_SETTINGS["profile"]),
            lookback_hours=int(settings.get("lookback_hours", DEFAULT_SETTINGS["lookback_hours"])),
        )
        return [
            (
                "timeline.chrome_history",
                sensor,
                SensorSpec(
                    sensor_id="timeline.chrome_history",
                    display_name="Chrome History",
                    description="Local Google Chrome browsing history ingested into the user timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode=str(settings.get("sync_mode", DEFAULT_SETTINGS["sync_mode"])),
                    polling_mode=getattr(sensor, "polling_mode", "interval"),
                    fields=_fields("sensors.chrome_history"),
                    metadata={
                        "source_type": "chrome_history",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "activation_flow": _activation_flow("sensors.chrome_history").model_dump(),
                    },
                ),
            )
        ]

    def build_temporal_summary_features(
        self,
        *,
        source_type: str,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> dict[str, object] | None:
        """Build browser-specific temporal summary features from Chrome history events."""

        _ = summary_category, period_start, period_end
        if source_type != "chrome_history":
            return None

        domain_counter: Counter[str] = Counter()
        visit_count = 0
        timestamps: list[float] = []
        for event in events:
            metadata = event.get("metadata_json")
            if not isinstance(metadata, dict):
                continue
            timeline = metadata.get("timeline")
            if not isinstance(timeline, dict):
                continue
            provenance = timeline.get("provenance")
            if not isinstance(provenance, dict):
                continue
            domain = str(provenance.get("domain") or "").strip().lower()
            if not domain:
                continue
            domain_counter[domain] += 1
            visit_count += max(1, int(provenance.get("merged_visit_count") or 1))
            if event.get("timestamp") is not None:
                timestamps.append(float(event["timestamp"]))

        if not domain_counter:
            return None

        top_domains = [
            {"domain": domain, "count": count}
            for domain, count in domain_counter.most_common(3)
        ]
        revisit_domains = [
            domain
            for domain, count in domain_counter.most_common()
            if count >= 2
        ]
        unique_domain_count = len(domain_counter)
        top_domain = top_domains[0]["domain"] if top_domains else None
        top_domain_count = int(top_domains[0]["count"]) if top_domains else 0
        focus_share = (top_domain_count / len(events)) if events else 0.0
        session_count = 1
        if timestamps:
            ordered_timestamps = sorted(timestamps)
            session_count = 1
            for previous, current in zip(ordered_timestamps, ordered_timestamps[1:]):
                if current - previous > _SESSION_GAP_SECONDS:
                    session_count += 1

        summary_lines: list[str] = []
        if top_domains and top_domain:
            if focus_share >= 0.6:
                summary_lines.append(f"Browsing concentrated heavily on {top_domain}.")
            else:
                joined = " and ".join(item["domain"] for item in top_domains[:2])
                summary_lines.append(f"Browsing focused on {joined}.")
        if revisit_domains:
            joined = " and ".join(revisit_domains[:2])
            summary_lines.append(f"Repeated visits clustered around {joined}.")
        if unique_domain_count <= 3:
            summary_lines.append("Browsing stayed within a small set of sites.")
        if session_count >= 2:
            summary_lines.append(f"Browsing unfolded across {session_count} distinct sessions.")

        return {
            "feature_type": "chrome_history",
            "event_count": len(events),
            "visit_count": visit_count,
            "unique_domain_count": unique_domain_count,
            "focus_domain": top_domain,
            "focus_share": focus_share,
            "session_count": session_count,
            "top_domains": top_domains,
            "revisit_domains": revisit_domains,
            "summary_lines": summary_lines,
        }
