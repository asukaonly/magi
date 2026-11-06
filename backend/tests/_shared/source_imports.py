"""Resolve declared Python imports for architecture checks."""

import ast
from importlib.util import resolve_name


def imported_names(source, *, package):
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = (
                resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module or ""
            )
            imports.add(base)
            imports.update(f"{base}.{alias.name}" for alias in node.names)
    return imports
