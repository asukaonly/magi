#!/usr/bin/env python3
"""Audit Rust dependencies with an exact, source-verified GLib backport."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, order=True)
class AdvisoryKey:
    """Identify one advisory for one exact locked package release."""

    advisory_id: str
    package: str
    version: str


APPROVED_EXCEPTIONS: dict[AdvisoryKey, str] = {
    AdvisoryKey("RUSTSEC-2024-0429", "glib", "0.18.5"): (
        "The workspace uses the checksum-verified local crate with the upstream "
        "VariantStrIter safety fix, not the unpatched registry release."
    ),
}


def advisory_keys(report: dict[str, Any]) -> set[AdvisoryKey]:
    """Return exact advisory/package/version triples from cargo-audit JSON."""
    keys: set[AdvisoryKey] = set()
    vulnerabilities = report.get("vulnerabilities", {}).get("list")
    warnings = report.get("warnings", {})
    if not isinstance(vulnerabilities, list) or not isinstance(warnings, dict):
        raise ValueError("Malformed cargo-audit report")
    unsound = warnings.get("unsound", [])
    if not isinstance(unsound, list):
        raise ValueError("Malformed cargo-audit unsound warnings")
    for item in [*vulnerabilities, *unsound]:
        advisory = item.get("advisory", {})
        package = item.get("package", {})
        keys.add(
            AdvisoryKey(
                str(advisory.get("id", "")),
                str(package.get("name", "")),
                str(package.get("version", "")),
            )
        )
    return keys


def evaluate_report(
    report: dict[str, Any],
) -> tuple[set[AdvisoryKey], set[AdvisoryKey]]:
    """Return unexpected findings and approved exceptions that became stale."""
    found = advisory_keys(report)
    approved = set(APPROVED_EXCEPTIONS)
    return found - approved, approved - found


def validate_exception_context() -> list[str]:
    """Verify that each exception still has the reviewed dependency context."""
    failures: list[str] = []
    glib = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check-vendored-glib.py")],
        capture_output=True,
        check=False,
        text=True,
    )
    if glib.returncode:
        failures.append(f"GLib backport validation failed: {glib.stderr.strip()}")

    return failures


def _load_audit_report() -> tuple[dict[str, Any] | None, str | None]:
    try:
        result = subprocess.run(
            ["cargo", "audit", "--json"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        return None, "cargo-audit is not installed"

    try:
        report = json.loads(result.stdout)
        if (
            result.returncode not in (0, 1)
            or not isinstance(report, dict)
            or "error" in report
        ):
            return (
                None,
                f"cargo-audit failed: {result.stderr.strip() or result.stdout.strip()}",
            )
        advisory_keys(report)
        return report, None
    except json.JSONDecodeError as exc:
        details = result.stderr.strip() or result.stdout.strip()
        return None, f"cargo-audit did not return valid JSON: {exc}; {details}"
    except (ValueError, TypeError, AttributeError) as exc:
        return None, f"cargo-audit returned an invalid report: {exc}"


def _describe(key: AdvisoryKey) -> str:
    return f"{key.advisory_id}: {key.package} {key.version}"


def main() -> int:
    report, error = _load_audit_report()
    if report is None:
        print(error, file=sys.stderr)
        return 1

    unexpected, stale = evaluate_report(report)
    context_failures = validate_exception_context()

    if unexpected:
        print("Unapproved Rust security advisories:", file=sys.stderr)
        for key in sorted(unexpected):
            print(f"- {_describe(key)}", file=sys.stderr)
    if stale:
        print("Stale Rust advisory exceptions must be removed:", file=sys.stderr)
        for key in sorted(stale):
            print(f"- {_describe(key)}", file=sys.stderr)
    if context_failures:
        print("Rust advisory exception context changed:", file=sys.stderr)
        for failure in context_failures:
            print(f"- {failure}", file=sys.stderr)
    if unexpected or stale or context_failures:
        return 1

    print("Rust dependency audit passed with reviewed, exact exceptions:")
    for key, reason in sorted(APPROVED_EXCEPTIONS.items()):
        print(f"- {_describe(key)}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
