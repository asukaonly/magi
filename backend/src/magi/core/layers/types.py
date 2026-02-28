"""
Shared enums and constants for five-layer agent architecture.
"""
from enum import Enum


class LayerTaskType(str, Enum):
    """Task kinds used by the new five-layer pipeline."""

    CHAT = "chat"
    INTERACTIVE = "interactive"
    COMPUTATION = "computation"
    BATCH = "batch"
    STUB_CAPABILITY = "stub_capability"


class StubCapability(str, Enum):
    """Capabilities reserved for future implementation."""

    MSG_NOTIFICATION = "msg_notification"
    DIGITAL_ASSET_STORAGE = "digital_asset_storage"
    SCHEDULE_TASK = "schedule_task"
    PHYSICAL_ENV_INTERVENTION = "physical_env_intervention"
    VIDEO_INPUT_SENSOR = "video_input_sensor"
    AUDIO_INPUT_SENSOR = "audio_input_sensor"
    EVENT_HOOK_SENSOR = "event_hook_sensor"
    CRON_EVENT_SENSOR = "cron_event_sensor"
