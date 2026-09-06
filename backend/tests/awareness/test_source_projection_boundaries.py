import ast
from pathlib import Path


SRC_ROOT = Path(__file__).parents[2] / "src" / "magi"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                found.append(node.module)
    return found


def test_source_event_projection_is_owned_by_consumers() -> None:
    legacy_mixed_projection = SRC_ROOT / "awareness" / "source_memory_projection.py"
    memory_projection = SRC_ROOT / "memory" / "source_event_projection.py"
    timeline_projection = SRC_ROOT / "timeline" / "source_event_projection.py"

    assert not legacy_mixed_projection.exists()
    assert memory_projection.exists()
    assert timeline_projection.exists()


def test_memory_and_timeline_do_not_import_legacy_awareness_projection() -> None:
    checked_paths = [
        SRC_ROOT / "memory" / "event_translation.py",
        SRC_ROOT / "timeline" / "subscribers" / "timeline_subscriber.py",
    ]

    violations = {
        str(path.relative_to(SRC_ROOT)): imports
        for path in checked_paths
        if (
            imports := [
                name
                for name in _imports(path)
                if name == "magi.awareness.source_memory_projection"
            ]
        )
    }

    assert violations == {}
