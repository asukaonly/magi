"""Resolve only explicitly selected library packages inside a worker."""

from __future__ import annotations

import importlib.abc
import importlib.util
from pathlib import Path
import sys
from typing import Any


class LibraryPackageFinder(importlib.abc.MetaPathFinder):
    """Avoid adding the package marketplace root to Python's import search path."""

    def __init__(self, roots: list[Path]) -> None:
        self.packages: dict[str, Path] = {}
        for root in roots:
            root = root.resolve()
            name = root.name
            if (
                not name.isidentifier()
                or name in {"magi", "magi_plugin_sdk"}
                or name in sys.stdlib_module_names
            ):
                raise ValueError("Invalid library import namespace")
            if not (root / "__init__.py").is_file():
                raise ValueError(
                    "Library dependency must be an exact Python package directory"
                )
            if name in self.packages:
                raise ValueError("Duplicate library import namespace")
            self.packages[name] = root

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        root = self.packages.get(fullname)
        if root is None:
            return None
        return importlib.util.spec_from_file_location(
            fullname, root / "__init__.py", submodule_search_locations=[str(root)]
        )


def install_library_imports(roots: list[Path]) -> None:
    finder = LibraryPackageFinder(roots)
    sys.meta_path.insert(0, finder)
