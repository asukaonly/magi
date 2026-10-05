"""Packaged plugin workers must match the source contract, including version bumps."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/install-plugin-worker-runtime.py"
spec = spec_from_file_location("install_plugin_worker_runtime", SCRIPT)
module = module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "runtime_version,protocol,metadata_version,valid",
    [
        ("0.9.8", 7, "0.9.8", True),
        ("0.9.7", 7, "0.9.8", False),
        ("0.9.8", 6, "0.9.8", False),
        ("0.9.8", 7, "0.9.7", False),
    ],
)
def test_probe_executes_against_installed_source_and_metadata(
    tmp_path, monkeypatch, runtime_version, protocol, metadata_version, valid
):
    import subprocess
    import sys
    import venv

    real_run = subprocess.run
    environment = tmp_path / "worker"
    venv.EnvBuilder(with_pip=False).create(environment)
    executable = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    site = Path(
        real_run(
            [
                str(executable),
                "-I",
                "-c",
                "import sysconfig; print(sysconfig.get_paths()['purelib'])",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    installed = site / "magi_plugin_sdk"
    installed.mkdir()
    (installed / "__init__.py").touch()
    (installed / "runtime.py").write_text(
        f"SDK_VERSION={runtime_version!r}\nPLUGIN_PROTOCOL_VERSION={protocol}\n"
    )
    for name in ("worker", "process_owner"):
        (installed / f"{name}.py").write_text("def main(): pass\n")
    (installed / "transport.py").write_text("def pack(*args): pass\ndef read_frame(*args): pass\n")
    metadata = site / f"magi_plugin_sdk-{metadata_version}.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: magi-plugin-sdk\nVersion: {metadata_version}\n"
    )
    sdk = tmp_path / "sdk"
    package = sdk / "src/magi_plugin_sdk"
    package.mkdir(parents=True)
    (sdk / "pyproject.toml").write_text("[project]\nname='magi-plugin-sdk'\nversion='0.9.8'\n")
    (package / "runtime.py").write_text('SDK_VERSION = "0.9.8"\n')
    (package / "versioning.py").write_text("PLUGIN_PROTOCOL_VERSION = 7\n")
    calls = []

    def install_or_probe(args, **kwargs):
        calls.append(args)
        if "pip" in args:
            return subprocess.CompletedProcess(args, 0)
        return real_run(args, capture_output=True, text=True, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", install_or_probe)
    if valid:
        module.install_worker_runtime(executable, sdk)
    else:
        with pytest.raises(subprocess.CalledProcessError) as error:
            module.install_worker_runtime(executable, sdk)
        assert "AssertionError" in error.value.stderr
    assert len(calls) == 2


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
