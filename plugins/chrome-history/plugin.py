"""Chrome history timeline plugin."""
from __future__ import annotations

from magi.plugins import ActivationFlowSpec, ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .chrome_reader import DEFAULT_MACOS_CHROME_ROOT
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
    "edge_whitelist": ["VISITED", "VIEWED"],
    "initial_sync_policy": "lookback_days",
    "initial_sync_lookback_days": 7,
    "initial_sync_configured": False,
}


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
        ExtensionFieldSpec(
            key=f"{prefix}.edge_whitelist",
            type="tags",
            label="Edge Whitelist",
            description="Relationship edge types this source may write into the user graph.",
            default=["VISITED", "VIEWED"],
            section="analysis",
            surface="timeline",
            order=80,
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
            source_path=str(settings.get("source_path") or DEFAULT_MACOS_CHROME_ROOT),
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
