"""Backward-compatibility shim -> :mod:`magi.control.permission`.

Re-export (not a ``sys.modules`` alias): aliasing a *package* corrupts
relative-import resolution for its submodules. Leaf submodules under this
package are aliased individually so identity and monkeypatching match.
"""

from __future__ import annotations

from magi.control.permission import *  # noqa: F401,F403
from magi.control.permission import __all__  # noqa: F401
