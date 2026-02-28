"""Stub modules for five-layer architecture."""

from .action_capabilities import StubActionCapabilities
from .sensors import StubSensor, build_default_stub_sensors

__all__ = [
    "StubActionCapabilities",
    "StubSensor",
    "build_default_stub_sensors",
]
