from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "rust_github_advisories", ROOT / "scripts/check-rust-github-advisories.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def affected(*events):
    return {
        "package": {"name": "tauri", "ecosystem": "crates.io"},
        "ranges": [{"type": "SEMVER", "events": list(events)}],
    }


@pytest.mark.parametrize(
    "version,expected",
    [
        ("2.10.3", True),
        ("2.11.0", True),
        ("2.11.1", False),
        ("2.11.1+build.1", False),
        ("2.11.1-rc.1", True),
        ("1.0.0", False),
    ],
)
def test_origin_advisory_excludes_fixed_release(version, expected) -> None:
    assert (
        MODULE.affected_version(
            version, affected({"introduced": "2.0.0"}, {"fixed": "2.11.1"})
        )
        is expected
    )


def test_multiple_intervals_and_inclusive_endpoints() -> None:
    item = affected(
        {"introduced": "0"},
        {"fixed": "0.8.6"},
        {"introduced": "0.9.0"},
        {"last_affected": "0.9.2"},
        {"introduced": "0.10.0"},
        {"limit": "0.10.1"},
    )
    for version in ["0.7.3", "0.9.2", "0.10.0"]:
        assert MODULE.affected_version(version, item)
    for version in ["0.8.6", "0.9.3", "0.10.1"]:
        assert not MODULE.affected_version(version, item)


def test_open_interval_explicit_versions_and_abbreviated_bounds() -> None:
    assert MODULE.affected_version("0.21.0", affected({"introduced": "0.20"}))
    assert MODULE.affected_version("1.0.0+build", {"versions": ["1.0.0"]})


@pytest.mark.parametrize(
    "item",
    [
        affected(),
        affected({"fixed": "1.0.0"}),
        affected({"introduced": "2.0.0"}, {"fixed": "1.0.0"}),
        affected({"introduced": "0"}, {"unknown": "1.0.0"}),
        {"ranges": [{"type": "GIT", "events": []}]},
    ],
)
def test_unsupported_or_corrupt_ranges_fail_closed(item) -> None:
    with pytest.raises(ValueError):
        MODULE.affected_version("1.0.0", item)


def test_each_locked_version_is_checked_but_local_patch_is_separate() -> None:
    packages = [
        {
            "name": "tauri",
            "version": v,
            "source": "registry+https://github.com/rust-lang/crates.io-index",
        }
        for v in ["2.10.3", "2.11.1"]
    ]
    packages.append({"name": "tauri", "version": "2.0.0"})
    records = [
        {
            "id": "GHSA-7gmj-67g7-phm9",
            "affected": [affected({"introduced": "2.0.0"}, {"fixed": "2.11.1"})],
        }
    ]
    assert MODULE.find_advisories(packages, records) == {
        ("GHSA-7gmj-67g7-phm9", "tauri", "2.10.3")
    }


def archive(records):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        for name, record in records.items():
            output.writestr(name, json.dumps(record))
    return data.getvalue()


def test_withdrawn_records_are_excluded_and_empty_databases_fail() -> None:
    record = {"id": "GHSA-7gmj-67g7-phm9", "affected": [affected({"introduced": "0"})]}
    withdrawn = {"id": "GHSA-3pv8-6f4r-ffg2", "withdrawn": "2026-01-01T00:00:00Z"}
    assert MODULE.read_advisories(
        archive({record["id"] + ".json": record, withdrawn["id"] + ".json": withdrawn})
    ) == [record]
    with pytest.raises(ValueError):
        MODULE.read_advisories(archive({}))


def test_download_sends_no_inventory_or_request_payload(monkeypatch) -> None:
    requests = []

    def fake_open(url, **kwargs):
        requests.append((url, kwargs))
        return io.BytesIO(b"public archive")

    monkeypatch.setattr(MODULE, "urlopen", fake_open)
    assert MODULE.download_database() == b"public archive"
    assert requests == [(MODULE.DATABASE_URL, {"timeout": 45})]


def test_network_failure_returns_failure(monkeypatch) -> None:
    monkeypatch.setattr(MODULE.sys, "argv", ["check-rust-github-advisories.py"])
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *args, **kwargs: MODULE.subprocess.CompletedProcess(args[0], 0),
    )

    def unavailable():
        raise OSError("Network unavailable")

    monkeypatch.setattr(MODULE, "download_database", unavailable)
    assert MODULE.main() == 1


def test_vendored_glib_is_still_checked_for_new_advisories() -> None:
    item = affected({"introduced": "0"})
    item["package"]["name"] = "glib"
    records = [{"id": "GHSA-aaaa-bbbb-cccc", "affected": [item]}]
    packages = [{"name": "glib", "version": "0.18.5"}]
    assert MODULE.find_advisories(packages, records) == {
        ("GHSA-aaaa-bbbb-cccc", "glib", "0.18.5")
    }


@pytest.mark.parametrize(
    "packages",
    [
        [],
        [
            {
                "name": "example",
                "version": "1.0.0",
                "source": "git+https://example.com/project",
            }
        ],
    ],
)
def test_unscanned_dependency_graph_cannot_pass(packages) -> None:
    with pytest.raises(ValueError):
        MODULE.find_advisories(packages, [])


def test_matcher_dependency_is_available_to_backend_test_contributors() -> None:
    import tomllib

    requirement = (ROOT / "scripts/security-audit-requirements.txt").read_text().strip()
    backend = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())
    assert requirement in backend["project"]["optional-dependencies"]["dev"]
