"""
Reserved sensor stubs for future multimodal/event integrations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..types import StubCapability


@dataclass
class StubSensor:
    """Metadata-only sensor placeholder."""

    name: str
    capability: StubCapability
    enabled: bool = False

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "capability": self.capability.value,
            "status": "enabled" if self.enabled else "disabled",
        }


def build_default_stub_sensors() -> list[StubSensor]:
    """Create default reserved sensor placeholders."""
    return [
        StubSensor(name="video_input_sensor", capability=StubCapability.VIDEO_INPUT_SENSOR),
        StubSensor(name="audio_input_sensor", capability=StubCapability.AUDIO_INPUT_SENSOR),
        StubSensor(name="event_hook_sensor", capability=StubCapability.EVENT_HOOK_SENSOR),
        StubSensor(name="cron_event_sensor", capability=StubCapability.CRON_EVENT_SENSOR),
    ]
