"""
自感知模块 - 核心数据结构
"""
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional, List
import time


class PerceptionType(Enum):
    """感知类型"""
    AUDIO = "audio"          # 音频
    VIDEO = "video"          # 视频
    TEXT = "text"            # 文本
    IMAGE = "image"          # 图像
    SENSOR = "sensor"        # 传感器数据
    EVENT = "event"          # 事件


class TriggerMode(Enum):
    """触发模式"""
    POLL = "poll"            # 轮询模式
    EVENT = "event"          # 事件模式
    HYBRID = "hybrid"        # 混合模式


@dataclass
class Perception:
    """
    感知数据
    """
    type: str                 # 感知类型
    data: Any                 # 感知数据
    timestamp: float           # 时间戳
    source: str                # 感知源标识
    priority: int = 0          # 优先级（0=普通，1=重要，2=紧急）
    metadata: dict = None       # 额外元数据

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
