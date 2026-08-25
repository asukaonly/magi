from __future__ import annotations

import importlib.util
import json
import logging
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
    assert "/api/messages/history" not in inventory["rust_native_routes"]
    assert "/api/messages/trace" not in inventory["rust_native_routes"]
    assert inventory["python_routes"]["/api/messages/history"] == ["GET"]
    assert inventory["python_routes"]["/api/messages/trace"] == ["GET"]
    assert "/api/memory/statistics" not in inventory["rust_native_routes"]
    assert inventory["python_routes"]["/api/memory/statistics"] == ["GET"]
    assert inventory["python_routes"]["/api/memory/l0/sessions"] == ["GET"]
    assert inventory["python_routes"][
        "/api/memory/l0/workbench/{session_id}"
    ] == ["GET"]
    assert inventory["python_routes"]["/api/config/"] == ["GET", "PUT"]


def test_gateway_api_contract_rejects_new_public_business_route() -> None:
    root = Path(__file__).resolve().parents[3]
    checker = _load_contract_checker(root)
    manifest = json.loads(
        (root / "contracts" / "api" / "gateway_routes.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["access_policy"]["public_native_routes"].append("/api/ready")

    errors = checker.validate_access_policy(manifest)

    assert "Only /api/health may be a public native route" in errors


def test_contract_checker_closes_runtime_log_handlers(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    checker = _load_contract_checker(root)
    log_path = tmp_path / "logs" / "contract.log"
    log_path.parent.mkdir()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    logger = logging.getLogger("magi.tests.gateway_contract_cleanup")
    logger.addHandler(handler)

    try:
        checker.close_log_handlers_in_directory(tmp_path)

        assert handler not in logger.handlers
        assert handler.stream is None
        log_path.unlink()
        assert not log_path.exists()
    finally:
        logger.removeHandler(handler)
        handler.close()
