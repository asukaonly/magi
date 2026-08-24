"""Concrete TaskAgent implementations.

Exports are loaded lazily (PEP 562) so that importing a *sibling* submodule
does not eagerly pull in the others. ``ChatTaskAgent`` was relocated to
``magi.chat.task_agent.chat_task_agent`` in P2 Task 3 and is no longer
re-exported here.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .default_task_agent import DefaultTaskAgent
    from .timeline_task_agent import TimelineTaskAgent

_LAZY_EXPORTS = {
    "DefaultTaskAgent": ".default_task_agent",
    "TimelineTaskAgent": ".timeline_task_agent",
}

__all__ = [
    "DefaultTaskAgent",
    "TimelineTaskAgent",
]


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(module_path, __name__)
    return getattr(module, name)


def __dir__():
    return sorted(__all__)
