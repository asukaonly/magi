"""Packaged plugin workers must match the source contract, including version bumps."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/install-plugin-worker-runtime.py"
spec = spec_from_file_location("install_plugin_worker_runtime", SCRIPT)
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_probe_checks_source_and_installed_metadata_after_a_version_change(tmp_path, monkeypatch):
    sdk = tmp_path / "sdk"
    package = sdk / "src/magi_plugin_sdk"
    package.mkdir(parents=True)
    (sdk / "pyproject.toml").write_text("[project]\nname='magi-plugin-sdk'\nversion='0.9.8'\n")
    (package / "runtime.py").write_text('SDK_VERSION = "0.9.8"\n')
    (package / "versioning.py").write_text('PLUGIN_PROTOCOL_VERSION = 7\n')
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda args, **kwargs: calls.append(args))
    module.install_worker_runtime(tmp_path / "python", sdk)
    assert calls[1][-2:] == ["0.9.8", "7"]
    assert "version('magi-plugin-sdk')==SDK_VERSION" in calls[1][-3]
    assert calls[1][1:4] == ["-I", "-S", "-c"]


def test_missing_protocol_does_not_install_an_unverifiable_package(tmp_path, monkeypatch):
    sdk = tmp_path / "sdk"
    package = sdk / "src/magi_plugin_sdk"
    package.mkdir(parents=True)
    (sdk / "pyproject.toml").touch()
    (package / "runtime.py").write_text('SDK_VERSION = "0.9.8"\n')
    (package / "versioning.py").write_text('OTHER = 7\n')
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must reject before installation"))
    with pytest.raises(ValueError, match="SDK identity is missing"):
        module.install_worker_runtime(tmp_path / "python", sdk)
