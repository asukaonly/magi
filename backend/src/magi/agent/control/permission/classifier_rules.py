"""Backward-compatibility shim -> :mod:`magi.control.permission.classifier_rules`.

Aliases this old module path to the canonical module *object* so that
attribute lookups, monkeypatching, and identity all match exactly.
The plugin-scope actuator tools / skills still import via this path; they relocate to the control layer in Phase 4."""

from __future__ import annotations

import sys

import magi.control.permission.classifier_rules as _canonical

sys.modules[__name__] = _canonical
