"""Agent control plane.

This package hosts the cross-cutting agent interaction primitives that
sit between the LLM-driven tool loop and the user:

* ``common``      — shared async primitives (``InteractionBroker``)
* ``permission``  — tool permission gateway, risk classifier, kill-list,
                    persistent rules
* ``settings``    — global + per-session control-plane settings

The eventual ``plan/``, ``todo/`` and ``ask/`` subpackages will land in
later phases; this initial drop ships only the permission spine plus the
shared broker they will reuse.
"""

from __future__ import annotations

__all__: list[str] = []
