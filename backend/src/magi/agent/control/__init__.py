"""Backward-compatibility shim package.

The control plane moved to :mod:`magi.control` as part of the
Control-Plane Extraction (ADR-0001, Phase 3). This package re-exports the
SAME objects from the new location; its submodules alias the canonical
modules so attribute lookups, monkeypatching, and identity all match.
Plugin-scope actuator tools (``tools/builtin``) and ``skills`` still
import via these shims; they relocate to the control layer in Phase 4.

Note: this package ``__init__`` is a re-export (not a ``sys.modules``
alias) on purpose. Aliasing a *package* corrupts relative-import
resolution for its submodules, so only leaf submodules are aliased.
"""

from __future__ import annotations

from magi.control import *  # noqa: F401,F403
from magi.control import __all__  # noqa: F401
