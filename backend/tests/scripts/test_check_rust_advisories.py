from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "check-rust-advisories.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_rust_advisories", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _finding(advisory_id: str, package: str, version: str) -> dict[str, object]:
    return {
        "advisory": {"id": advisory_id},
        "package": {"name": package, "version": version},
    }


def test_evaluate_report_accepts_only_exact_reviewed_findings() -> None:
    module = _load_script()
    report = {
        "vulnerabilities": {
            "list": [
                _finding(key.advisory_id, key.package, key.version)
                for key in module.APPROVED_EXCEPTIONS
            ]
        }
    }

    assert module.evaluate_report(report) == (set(), set())


def test_evaluate_report_rejects_changed_package_version() -> None:
    module = _load_script()
    findings = [
        _finding(key.advisory_id, key.package, key.version)
        for key in module.APPROVED_EXCEPTIONS
        if key.package != "quick-xml"
    ]
    findings.extend(
        [
            _finding("RUSTSEC-2026-0194", "quick-xml", "0.37.6"),
            _finding("RUSTSEC-2026-0195", "quick-xml", "0.37.6"),
        ]
    )

    unexpected, stale = module.evaluate_report(
        {"vulnerabilities": {"list": findings}}
    )

    assert {key.version for key in unexpected} == {"0.37.6"}
    assert {key.version for key in stale} == {"0.37.5"}


def test_evaluate_report_requires_stale_exceptions_to_be_removed() -> None:
    module = _load_script()

    unexpected, stale = module.evaluate_report({"vulnerabilities": {"list": []}})

    assert unexpected == set()
    assert stale == set(module.APPROVED_EXCEPTIONS)


def test_package_label_normalizes_cargo_tree_lines() -> None:
    module = _load_script()

    assert module._package_label("quick-xml v0.37.5") == "quick-xml v0.37.5"
    assert (
        module._package_label("└── magi-desktop v0.1.23 (/workspace/frontend)")
        == "magi-desktop v0.1.23"
    )
    assert module._package_label("    [build-dependencies]") is None
