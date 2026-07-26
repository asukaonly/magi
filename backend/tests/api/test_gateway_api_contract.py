from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_contract_checker(root: Path) -> ModuleType:
    checker_path = root / "scripts" / "check-api-contract.py"
    spec = importlib.util.spec_from_file_location("gateway_api_contract_checker", checker_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gateway_api_contract_manifest_matches_router_inventory() -> None:
    root = Path(__file__).resolve().parents[3]
    checker = _load_contract_checker(root)

    errors, inventory = checker.validate_contract(
        root,
        root / "contracts" / "api" / "gateway_routes.json",
    )

    assert errors == []
    assert "/api/memory/statistics" not in inventory["rust_native_routes"]
    assert inventory["python_routes"]["/api/memory/statistics"] == ["GET"]
    assert inventory["python_routes"]["/api/memory/l0/sessions"] == ["GET"]
    assert inventory["python_routes"][
        "/api/memory/l0/workbench/{session_id}"
    ] == ["GET"]
    assert inventory["python_routes"]["/api/config/"] == ["GET", "PUT"]
