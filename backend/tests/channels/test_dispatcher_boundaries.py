import ast
from pathlib import Path


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                found.append(node.module)
            else:
                # backend/src/magi/channels/dispatcher.py
                package = ["magi", "channels"]
                keep = len(package) - node.level + 1
                if keep >= 0:
                    found.append(".".join([*package[:keep], node.module]))
    return found


def test_channel_dispatcher_does_not_depend_on_api_layer():
    path = Path(__file__).parents[2] / "src" / "magi" / "channels" / "dispatcher.py"
    violations = [name for name in _imports(path) if name.startswith("magi.api")]

    assert violations == []
