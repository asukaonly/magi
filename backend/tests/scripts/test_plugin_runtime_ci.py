"""Exercise immutable pair admission, native selection and real checker failure gates."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "plugin_runtime_ci", ROOT / "scripts/plugin_runtime_ci.py"
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize("reference", ["main", "v0.2.0", "abc123", "a" * 39])
def test_mutable_or_short_sdk_pin_is_rejected(tmp_path, reference):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        f"magi-plugin-sdk @ git+https://github.com/asukaonly/magi.git@{reference}#subdirectory=sdk\n"
    )
    with pytest.raises(ValueError, match="exact Magi SDK VCS pin"):
        gate.resolve_host_pin(requirements)


def test_sdk_pin_resolution_rejects_duplicate_and_foreign_repositories(tmp_path):
    requirements = tmp_path / "requirements.txt"
    pin = "a" * 40
    line = f"magi-plugin-sdk @ git+https://github.com/asukaonly/magi.git@{pin}#subdirectory=sdk\n"
    requirements.write_text("# Public contract\npydantic==2.13.4\n" + line)
    assert gate.resolve_host_pin(requirements) == pin
    for invalid in [
        line + line,
        line.replace("asukaonly", "other-owner"),
        line.replace("=sdk", "=backend"),
    ]:
        requirements.write_text(invalid)
        with pytest.raises(ValueError):
            gate.resolve_host_pin(requirements)


def test_checkout_sha_must_match_exactly():
    evidence = gate.checkout_evidence(ROOT)
    assert gate.checkout_evidence(ROOT, evidence["head"])["head"] == evidence["head"]
    for expected in ["main", evidence["head"][:10], "0" * 40]:
        with pytest.raises(ValueError, match="Checkout mismatch"):
            gate.checkout_evidence(ROOT, expected)


def test_new_process_test_files_are_selected_without_missing_future_paths(tmp_path):
    scripts = tmp_path / "backend/tests/scripts"
    scripts.mkdir(parents=True)
    (scripts / "test_plugin_runtime_ci.py").touch()
    plugins = tmp_path / "backend/tests/plugins"
    plugins.mkdir()
    for name in ["runtime", "callback_lifecycle"]:
        (plugins / f"test_process_{name}.py").touch()
    (plugins / "test_worker_sdk_admission.py").touch()
    watch = plugins / "test_process_source_watch.py"
    assert str(watch) not in gate.test_selection(tmp_path)
    watch.touch()
    assert str(watch) in gate.test_selection(tmp_path)
    (plugins / "test_process_runtime.py").unlink()
    with pytest.raises(ValueError, match="Required worker gate"):
        gate.test_selection(tmp_path)


def test_stage_timeout_terminates_real_process(tmp_path):
    result = gate.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=0.2,
    )
    assert result["timed_out"]
    assert result["returncode"] != 0
    assert result["elapsed_seconds"] < 10


@pytest.fixture
def checker_repository(tmp_path):
    repo = tmp_path / "companion"
    repo.mkdir()
    for arguments in [
        ["init"],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "test: initialize fixture",
        ],
    ]:
        subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)
    return repo


def write_package(repo, plugin_id, platforms, *, broken=False):
    package = repo / "plugins" / plugin_id
    package.mkdir(parents=True)
    (package / "plugin.toml").write_text(
        f'[plugin]\nid = "{plugin_id}"\nname = "Probe"\nversion = "0.2.0"\n'
        'protocol_version = 2\nmin_sdk_version = "0.2.0"\nexecution_mode = "trusted_process"\n'
        f'platforms = {json.dumps(platforms)}\nentry_class = "Probe"\ncontribution_types = []\n'
    )
    (package / "plugin.py").write_text(
        "raise RuntimeError('Native bootstrap failure')\n"
        if broken
        else "from magi_plugin_sdk import Plugin\nclass Probe(Plugin): pass\n"
    )


def run_checker(repo, tmp_path):
    report = tmp_path / "runtime.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check-plugin-runtime.py"),
            "--plugins-repo",
            str(repo),
            "--python",
            sys.executable,
            "--install-dependencies",
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert report.is_file(), completed.stdout + completed.stderr
    return completed, json.loads(report.read_text())


def test_native_checker_launches_two_workers_and_never_imports_unsupported(
    checker_repository, tmp_path
):
    repo = checker_repository
    write_package(repo, "native-probe", [gate.native_platform()])
    write_package(repo, "excluded-probe", ["ios"], broken=True)
    completed, report = run_checker(repo, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert report["summary"] == {"unsupported": 1, "passed": 1, "libraries": 0, "workers": 2}
    native = next(entry for entry in report["packages"] if entry["plugin_id"] == "native-probe")
    pids = [connection["pid"] for connection in native["connections"]]
    assert len(set(pids)) == 2
    assert all(pid != os.getpid() for pid in pids)
    if os.name == "nt":
        assert all(connection["windows_job"] for connection in native["connections"])
    assert not list(repo.glob("plugins/*/.deps"))
    assert "magi-runtime-check-home-" in report["runtime_home"]
    assert not Path(report["runtime_home"]).exists()


@pytest.mark.parametrize("platforms", [["ios"], []])
def test_no_native_pass_or_bootstrap_failure_fails_gate(checker_repository, tmp_path, platforms):
    write_package(checker_repository, "broken-probe", platforms, broken=True)
    completed, report = run_checker(checker_repository, tmp_path)
    assert completed.returncode == 1
    assert not report["summary"].get("passed")
