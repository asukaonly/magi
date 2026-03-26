"""Terminal History timeline plugin."""
from __future__ import annotations

import sys
from typing import Any

from magi.plugins import (
    ActivationFlowSpec,
    ExtensionFieldOption,
    ExtensionFieldSpec,
    Plugin,
    SensorSpec,
)

from .filters import BUILTIN_SENSITIVE_KEYWORDS
from .reader import TerminalHistoryReader
from .sensor import TerminalHistorySensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_interval_minutes": 15,
    "initial_sync_policy": "lookback_days",
    "initial_sync_lookback_days": 7,
    "initial_sync_configured": False,
    "sensitive_mode": "redact",
    "sensitive_keywords": [],
    "dedup_window_seconds": 60,
    "default_retention_mode": "analyze_only",
}


def _activation_flow(prefix: str) -> ActivationFlowSpec:
    """Define activation flow for first-time setup."""
    return ActivationFlowSpec(
        title="Enable Terminal History",
        description=(
            "Terminal history contains commands you've executed. "
            "Choose how much history should be imported when this source is enabled for the first time."
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
                description="Decide how much command history should be imported.",
                default="lookback_days",
                options=[
                    ExtensionFieldOption(label="Sync full history", value="full"),
                    ExtensionFieldOption(label="Sync recent days", value="lookback_days"),
                    ExtensionFieldOption(label="Only new commands from now", value="from_now"),
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
    """Define all settings fields for the Terminal History plugin."""
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enabled",
            description="Whether terminal history sync is active.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="number",
            label="Sync Interval (minutes)",
            description="How often to check for new terminal commands.",
            default=15,
            min=1,
            max=1440,
            section="general",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How terminal history data should be retained.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Full Retention", value="full"),
            ],
            section="retention",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sensitive_mode",
            type="select",
            label="Sensitive Command Mode",
            description="How to handle commands containing sensitive information.",
            default="redact",
            options=[
                ExtensionFieldOption(label="Redact sensitive parts", value="redact"),
                ExtensionFieldOption(label="Block entire command", value="block"),
            ],
            section="privacy",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sensitive_keywords",
            type="tags",
            label="Additional Sensitive Keywords",
            description="Extra keywords to detect sensitive commands (built-in: password, token, api_key, etc.)",
            default=[],
            section="privacy",
            surface="timeline",
            order=50,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.dedup_window_seconds",
            type="number",
            label="Dedup Window (seconds)",
            description="Time window for session-based command deduplication.",
            default=60,
            min=0,
            max=3600,
            section="general",
            surface="timeline",
            order=60,
        ),
    ]


class TerminalHistoryPlugin(Plugin):
    """Registers the Terminal History timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        """Get sensor specifications for Terminal History.

        Returns:
            List of sensor tuples (sensor_id, sensor_instance, sensor_spec)
        """
        # Check platform - only supported on Darwin
        if sys.platform != "darwin":
            return []

        # Get settings
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("terminal_history", {}))

        source_enabled = bool(settings.get("enabled", DEFAULT_SETTINGS["enabled"]))

        # Check history availability (but still return sensor spec even if not available)
        reader = None
        if source_enabled:
            try:
                reader = TerminalHistoryReader()
                if not reader.is_available():
                    reader = None
            except Exception:
                reader = None

        # Create sensor (reader may be None if not available)
        sensor = TerminalHistorySensor(
            retention_mode=str(settings.get("default_retention_mode", DEFAULT_SETTINGS["default_retention_mode"])),
            reader=reader,
        )

        # Get sync interval
        sync_interval_minutes = settings.get("sync_interval_minutes", DEFAULT_SETTINGS["sync_interval_minutes"])

        return [
            (
                "timeline.terminal_history",
                sensor,
                SensorSpec(
                    sensor_id="timeline.terminal_history",
                    display_name="Terminal History",
                    description="Terminal command history ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode="interval",
                    polling_mode="interval",
                    fields=_fields("sensors.terminal_history"),
                    metadata={
                        "source_type": "terminal_history",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "sync_interval_minutes": sync_interval_minutes,
                        "activation_flow": _activation_flow("sensors.terminal_history").model_dump(),
                    },
                ),
            )
        ]
