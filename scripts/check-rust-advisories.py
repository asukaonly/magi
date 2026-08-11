#!/usr/bin/env python3
"""Audit Rust dependencies with narrow, self-expiring exceptions."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True, order=True)
class AdvisoryKey:
    """Identify one advisory for one exact locked package release."""

    advisory_id: str
    package: str
    version: str


APPROVED_EXCEPTIONS: dict[AdvisoryKey, str] = {
    AdvisoryKey("RUSTSEC-2026-0194", "quick-xml", "0.37.5"): (
        "The only reverse path is tauri-winrt-notification 0.7.2, which uses "
        "quick-xml only for escaping notification strings, not XML parsing."
    ),
    AdvisoryKey("RUSTSEC-2026-0195", "quick-xml", "0.37.5"): (
        "The only reverse path is tauri-winrt-notification 0.7.2, which uses "
        "quick-xml only for escaping notification strings, not XML parsing."
    ),
    AdvisoryKey("RUSTSEC-2026-0235", "rkyv", "0.7.46"): (
        "rkyv is an optional rust_decimal dependency and is not enabled by any "
        "workspace target or feature."
    ),
}

EXPECTED_QUICK_XML_PATH = {
    "quick-xml v0.37.5",
    "tauri-winrt-notification v0.7.2",
    "notify-rust v4.18.0",
    "tauri-plugin-notification v2.3.3",
    f"magi-desktop v{(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}",
}


def _package_label(line: str) -> str | None:
    """Extract a package label from one cargo-tree output line."""
    label = ANSI_ESCAPE_RE.sub("", line).lstrip(" │├└─")
    if not label or label.startswith("["):
        return None
    return label.split(" (/", maxsplit=1)[0].removesuffix(" (*)")


def advisory_keys(report: dict[str, Any]) -> set[AdvisoryKey]:
    """Return exact advisory/package/version triples from cargo-audit JSON."""
    keys: set[AdvisoryKey] = set()
    vulnerabilities = report.get("vulnerabilities", {}).get("list", [])
    for item in vulnerabilities:
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


def evaluate_report(report: dict[str, Any]) -> tuple[set[AdvisoryKey], set[AdvisoryKey]]:
    """Return unexpected findings and approved exceptions that became stale."""
    found = advisory_keys(report)
    approved = set(APPROVED_EXCEPTIONS)
    return found - approved, approved - found


def _run_cargo_tree(*args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CARGO_TERM_COLOR"] = "never"
    return subprocess.run(
        ["cargo", "tree", "--locked", "--target", "all", *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )


def validate_exception_context() -> list[str]:
    """Verify that each exception still has the reviewed dependency context."""
    failures: list[str] = []

    quick_xml = _run_cargo_tree("-i", "quick-xml@0.37.5")
    if quick_xml.returncode != 0:
        failures.append(f"quick-xml reverse-tree check failed: {quick_xml.stderr.strip()}")
    else:
        packages = {
            label
            for line in quick_xml.stdout.splitlines()
            if (label := _package_label(line)) is not None
        }
        if packages != EXPECTED_QUICK_XML_PATH:
            failures.append(
                "quick-xml 0.37.5 dependency path changed: "
                f"expected {sorted(EXPECTED_QUICK_XML_PATH)}, got {sorted(packages)}"
            )

    rkyv = _run_cargo_tree("--all-features", "-i", "rkyv@0.7.46")
    if rkyv.returncode != 0:
        failures.append(f"rkyv reachability check failed: {rkyv.stderr.strip()}")
    elif rkyv.stdout.strip():
        failures.append("rkyv 0.7.46 became reachable:\n" + rkyv.stdout.strip())

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
        return json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        details = result.stderr.strip() or result.stdout.strip()
        return None, f"cargo-audit did not return valid JSON: {exc}; {details}"


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
