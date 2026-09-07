from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
import sys
from types import ModuleType

import pytest

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

    unexpected, stale = module.evaluate_report({"vulnerabilities": {"list": findings}})

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
    assert (
        module._package_label(
            "\x1b[2m    \x1b[0m\x1b[2m└──\x1b[0m magi-desktop v0.1.24"
        )
        == "magi-desktop v0.1.24"
    )
    assert module._package_label("    [build-dependencies]") is None


def test_quick_xml_path_tracks_current_workspace_version() -> None:
    module = _load_script()
    version = (module.ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert f"magi-desktop v{version}" in module.EXPECTED_QUICK_XML_PATH


def test_cargo_tree_disables_colored_output(monkeypatch) -> None:
    module = _load_script()
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return module.subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module._run_cargo_tree("-i", "quick-xml@0.37.5")

    assert captured["env"]["CARGO_TERM_COLOR"] == "never"


def test_unsound_warnings_are_checked_even_without_vulnerabilities() -> None:
    module = _load_script()
    report = {
        "vulnerabilities": {"list": []},
        "warnings": {"unsound": [_finding("RUSTSEC-2099-0001", "example", "1.0.0")]},
    }
    unexpected, _ = module.evaluate_report(report)
    assert unexpected == {module.AdvisoryKey("RUSTSEC-2099-0001", "example", "1.0.0")}


def test_unmaintained_notices_do_not_hide_unsound_findings() -> None:
    module = _load_script()
    report = {
        "vulnerabilities": {"list": []},
        "warnings": {
            "unmaintained": [_finding("RUSTSEC-2099-0002", "example", "1.0.0")]
        },
    }
    assert module.advisory_keys(report) == set()


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"vulnerabilities": {"list": None}},
        {"vulnerabilities": {"list": []}, "warnings": {"unsound": {}}},
    ],
)
def test_malformed_audit_reports_cannot_pass(report) -> None:
    module = _load_script()
    with pytest.raises(ValueError):
        module.advisory_keys(report)


def test_exceptions_expire_at_the_review_deadline() -> None:
    module = _load_script()
    assert module.exception_review_failures(date(2026, 9, 7)) == []
    assert module.exception_review_failures(module.EXCEPTION_REVIEW_DEADLINE)


def test_failed_audit_process_cannot_return_a_clean_report(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: module.subprocess.CompletedProcess(
            args[0], 2, '{"vulnerabilities":{"list":[]}}', "Database unavailable"
        ),
    )
    report, error = module._load_audit_report()
    assert report is None
    assert "Database unavailable" in error
