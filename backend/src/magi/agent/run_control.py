"""Backward-compatibility shim -> :mod:`magi.control.run_control`.

``run_control`` moved to :mod:`magi.control.run_control` as part of the
Control-Plane Extraction (ADR-0001, Phase 3). This module aliases the old
import path to the canonical module *object* so attribute lookups,
monkeypatching, and identity all match exactly. The plugin-scope actuator
tools (``tools/builtin``) still import via this path; they relocate to the
control layer in Phase 4.
"""

from __future__ import annotations

import sys

import magi.control.run_control as _canonical

sys.modules[__name__] = _canonical
