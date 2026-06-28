"""Agent control plane.

This package hosts the cross-cutting agent interaction primitives that
sit between the LLM-driven tool loop and the user:

* ``common``      — shared async primitives (``InteractionBroker``)
* ``ask_service`` — ask-user lifecycle service used by runtime interaction
                    ports and control tools
* ``permission``  — tool permission gateway, risk classifier, kill-list,
                    persistent rules
* ``settings``    — global + per-session control-plane settings
"""

from __future__ import annotations

__all__: list[str] = []
