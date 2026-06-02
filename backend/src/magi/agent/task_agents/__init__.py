"""Concrete TaskAgent implementations.

Exports are loaded lazily (PEP 562) so that importing a *sibling* submodule
does not eagerly pull in ``chat_task_agent``. ``chat_task_agent`` constructs
the chat-driver services that now live in ``magi.chat.task_agent`` (relocated
in P2 Task 2); eager loading here would create an import cycle when one of
those relocated modules is imported before this package is initialized.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chat_task_agent import ChatTaskAgent
    from .default_task_agent import DefaultTaskAgent
    from .explore_task_agent import ExploreTaskAgent
    from .timeline_task_agent import TimelineTaskAgent

_LAZY_EXPORTS = {
    "ChatTaskAgent": ".chat_task_agent",
    "DefaultTaskAgent": ".default_task_agent",
    "ExploreTaskAgent": ".explore_task_agent",
    "TimelineTaskAgent": ".timeline_task_agent",
}

__all__ = [
    "ChatTaskAgent",
    "DefaultTaskAgent",
    "ExploreTaskAgent",
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
