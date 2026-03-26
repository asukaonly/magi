"""Git Activity timeline plugin."""
from __future__ import annotations

from typing import Any

from magi.plugins import (
    ExtensionFieldOption,
    ExtensionFieldSpec,
    Plugin,
    SensorSpec,
)

from .reader import is_git_repo
from .sensor import GitActivitySensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "repos": [],
    "sync_interval_minutes": 30,
    "initial_sync_policy": "lookback_days",
    "initial_sync_lookback_days": 30,
    "sensitive_mode": "redact",
    "sensitive_keywords": [],
    "default_retention_mode": "analyze_only",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Define all settings fields for the Git Activity plugin."""
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enabled",
            description="Whether git activity sync is active.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.repos",
            type="tags",
            label="Repositories",
            description="Git repository paths to monitor (e.g., ~/code/magi, ~/projects/app).",
            default=[],
            section="general",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="number",
            label="Sync Interval (minutes)",
            description="How often to check for new git activity.",
            default=30,
            min=5,
            max=1440,
            section="general",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How git activity data should be retained.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Full Retention", value="full"),
            ],
            section="retention",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.initial_sync_policy",
            type="select",
            label="Initial Sync Policy",
            description="How much history to import on first sync.",
            default="lookback_days",
            options=[
                ExtensionFieldOption(label="Full history", value="full"),
                ExtensionFieldOption(label="Lookback days", value="lookback_days"),
                ExtensionFieldOption(label="From now only", value="from_now"),
            ],
            section="sync",
            surface="timeline",
            order=50,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.initial_sync_lookback_days",
            type="number",
            label="Lookback Days",
            description="Days of history to import on first sync.",
            default=30,
            min=1,
            max=365,
            section="sync",
            surface="timeline",
            order=60,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sensitive_mode",
            type="select",
            label="Sensitive Message Mode",
            description="How to handle commit messages with sensitive content.",
            default="redact",
            options=[
                ExtensionFieldOption(label="Redact sensitive parts", value="redact"),
                ExtensionFieldOption(label="Block entirely", value="block"),
            ],
            section="privacy",
            surface="timeline",
            order=70,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sensitive_keywords",
            type="tags",
            label="Additional Sensitive Keywords",
            description="Extra keywords to detect in commit messages (built-in: password, secret, token, etc.)",
            default=[],
            section="privacy",
            surface="timeline",
            order=80,
        ),
    ]


class GitActivityPlugin(Plugin):
    """Registers the Git Activity timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        """Get sensor specifications for Git Activity.

        Returns:
            List of sensor tuples (sensor_id, sensor_instance, sensor_spec)
        """
        # Get settings
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("git_activity", {}))

        source_enabled = bool(settings.get("enabled", DEFAULT_SETTINGS["enabled"]))

        # Get configured repos (use empty list as default)
        repos = settings.get("repos", []) if source_enabled else []
        valid_repos = []
        for repo in repos:
            if isinstance(repo, str) and repo.strip() and is_git_repo(repo):
                valid_repos.append(repo.strip())

        # Create sensor with available repos (may be empty)
        sensor = GitActivitySensor(
            retention_mode=str(settings.get("default_retention_mode", DEFAULT_SETTINGS["default_retention_mode"])),
            repos=valid_repos,
        )

        # Get sync interval
        sync_interval_minutes = settings.get("sync_interval_minutes", DEFAULT_SETTINGS["sync_interval_minutes"])

        return [
            (
                "timeline.git_activity",
                sensor,
                SensorSpec(
                    sensor_id="timeline.git_activity",
                    display_name="Git Activity",
                    description="Git repository activity ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode="interval",
                    polling_mode="interval",
                    fields=_fields("sensors.git_activity"),
                    metadata={
                        "source_type": "git_activity",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "sync_interval_minutes": sync_interval_minutes,
                    },
                ),
            )
        ]
