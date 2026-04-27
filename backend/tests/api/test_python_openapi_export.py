from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_exporter(root: Path) -> ModuleType:
    exporter_path = root / "scripts" / "export-python-openapi.py"
    spec = importlib.util.spec_from_file_location("python_openapi_exporter", exporter_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_openapi_export_matches_ipc_route_boundary() -> None:
    root = Path(__file__).resolve().parents[3]
    exporter = _load_exporter(root)

    schema = exporter.build_openapi_schema(root)
    exporter.validate_schema(schema)

    paths = schema["paths"]
    assert "/api/messages/send" in paths
    assert "/api/personas/active" in paths
    assert "/api/metrics/runtime/overview" not in paths
    assert "/api/tasks" not in paths