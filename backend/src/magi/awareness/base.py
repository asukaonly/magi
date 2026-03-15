"""
Perception module - core data structures
"""
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional, List
import time


class PerceptionType(Enum):
    """Perception type"""
    AUDIO = "audio"          # audio
    VIDEO = "video"          # video
    TEXT = "text"            # text
    IMAGE = "image"          # image
    SENSOR = "sensor"        # sensor data
    EVENT = "event"          # event


class TriggerMode(Enum):
    """Trigger mode"""
    POLL = "poll"            # polling mode
    EVENT = "event"          # event mode
    HYBRID = "hybrid"        # hybrid mode


@dataclass
class Perception:
    """
    Perception data
    """
    type: str                 # perception type
    data: Any                 # perception data
    timestamp: float           # timestamp
    source: str                # perception source identifier
    priority: int = 0          # priority (0=normal, 1=important, 2=urgent)
    metadata: dict = None       # additional metadata

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
