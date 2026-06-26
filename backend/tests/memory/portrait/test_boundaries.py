import ast
from pathlib import Path


FORBIDDEN_PREFIXES = (
    "magi.chat",
    "magi.personality",
    "magi.llm",
    "magi.config",
    "magi.api",
)


def _absolute_import_from_relative(module: str, node: ast.ImportFrom) -> str | None:
    if node.module is None:
        return None
    parts = module.split(".")
    package_parts = parts[:-1]
    if node.level > 0:
        keep = len(package_parts) - node.level + 1
        if keep < 0:
            return None
        package_parts = package_parts[:keep]
    return ".".join([*package_parts, node.module])


def _module_name(path: Path) -> str:
    src_root = Path(__file__).parents[3] / "src"
    return ".".join(path.relative_to(src_root).with_suffix("").parts)


def _imports(path: Path) -> list[str]:
    module = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.append(node.module)
            else:
                absolute = _absolute_import_from_relative(module, node)
                if absolute:
                    found.append(absolute)
    return found


def test_memory_portrait_does_not_assemble_chat_persona_or_llm_runtime():
    package_root = Path(__file__).parents[3] / "src" / "magi" / "memory" / "portrait"
    violations: list[str] = []
    for path in sorted(package_root.glob("*.py")):
        for imported in _imports(path):
            if imported.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{path.name} -> {imported}")

    assert violations == []
