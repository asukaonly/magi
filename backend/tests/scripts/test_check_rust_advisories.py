from __future__ import annotations

import importlib.util
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


@pytest.mark.parametrize("package,version,advisory", [
    ("glib", "0.18.6", "RUSTSEC-2024-0429"),
    ("quick-xml", "0.37.5", "RUSTSEC-2026-0194"),
    ("quick-xml", "0.37.5", "RUSTSEC-2026-0195"),
    ("rkyv", "0.7.46", "RUSTSEC-2026-0235"),
])
def test_evaluate_report_rejects_unpatched_or_removed_exceptions(package, version, advisory):
    module = _load_script()
    findings = [_finding(advisory, package, version)]
    unexpected, _ = module.evaluate_report({"vulnerabilities": {"list": findings}})
    assert unexpected == {module.AdvisoryKey(advisory, package, version)}


def test_evaluate_report_requires_stale_exceptions_to_be_removed() -> None:
    module = _load_script()

    unexpected, stale = module.evaluate_report({"vulnerabilities": {"list": []}})

    assert unexpected == set()
    assert stale == set(module.APPROVED_EXCEPTIONS)


@pytest.mark.parametrize("returncode", [0, 1])
def test_only_verified_glib_sources_allow_the_remaining_exception(monkeypatch, returncode):
    module = _load_script()
    calls = []

    def verify(args, **kwargs):
        calls.append(args)
        return module.subprocess.CompletedProcess(args, returncode, "", "checksum mismatch")

    monkeypatch.setattr(module.subprocess, "run", verify)
    failures = module.validate_exception_context()
    assert calls == [[sys.executable, str(module.ROOT / "scripts/check-vendored-glib.py")]]
    assert bool(failures) == bool(returncode)
    if failures:
        assert "checksum mismatch" in failures[0]


@pytest.mark.parametrize("with_unsound", [False, True])
def test_unmaintained_notices_do_not_mask_unsound_findings(with_unsound) -> None:
    module = _load_script()
    report = {
        "vulnerabilities": {"list": []},
        "warnings": {
            "unsound": [_finding("RUSTSEC-2099-0001", "example", "1.0.0")] if with_unsound else [],
            "unmaintained": [_finding("RUSTSEC-2099-0002", "notice", "1.0.0")],
        },
    }
    unexpected, _ = module.evaluate_report(report)
    assert unexpected == (
        {module.AdvisoryKey("RUSTSEC-2099-0001", "example", "1.0.0")} if with_unsound else set()
    )


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
