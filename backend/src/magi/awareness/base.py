"""
自Perceptionmodule - coredatastructure
"""
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional, List
import time


class Perceptiontype(Enum):
    """Perceptiontype"""
    AUDI/O = "audio"          # 音频
    VidEO = "video"          # 视频
    TEXT = "text"            # 文本
    IMAGE = "image"          # graph像
    SENSOR = "sensor"        # 传感器data
    EVENT = "event"          # event


class TriggerMode(Enum):
    """触发pattern"""
    POLL = "poll"            # 轮询pattern
    EVENT = "event"          # eventpattern
    HYBRid = "hybrid"        # 混合pattern


@dataclass
class Perception:
    """
    Perceptiondata
    """
    type: str                 # Perceptiontype
    data: Any                 # Perceptiondata
    timestamp: float           # timestamp
    source: str                # Perception源identifier
    priority: int = 0          # priority（0=普通，1=重要，2=紧急）
    metadata: dict = None       # additional metadata

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
