#!/usr/bin/env python3
"""Install and validate the standalone SDK in staged desktop plugin Python."""

from __future__ import annotations

import argparse
import ast
import subprocess
from pathlib import Path


def expected_sdk_identity(sdk_directory: Path) -> tuple[str, int]:
    """Read literal identities from the source being packaged, without importing it."""
    def constant(module: str, name: str) -> object:
        path = sdk_directory / "src" / "magi_plugin_sdk" / module
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
        raise ValueError(f"SDK identity is missing: {name}")

    version = constant("runtime.py", "SDK_VERSION")
    protocol = constant("versioning.py", "PLUGIN_PROTOCOL_VERSION")
    if not isinstance(version, str) or type(protocol) is not int or protocol < 1:
        raise ValueError("SDK identity has an invalid type")
    return version, protocol


def install_worker_runtime(executable: Path, sdk_directory: Path) -> None:
    """Install a wheel-backed SDK; editable imports cannot work in a bundle."""
    executable = executable.absolute()
    sdk_directory = sdk_directory.resolve(strict=True)
    if not (sdk_directory / "pyproject.toml").is_file():
        raise ValueError("Worker SDK directory must contain pyproject.toml")
    sdk_version, protocol_version = expected_sdk_identity(sdk_directory)
    subprocess.run(
        [
            str(executable),
            "-I",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--upgrade",
            str(sdk_directory),
        ],
        check=True,
    )
    probe = (
        "import sys,sysconfig;from pathlib import Path;"
        "exe=Path(sys.executable).absolute();"
        "venv=next((p for p in (exe.parent,exe.parent.parent) if (p/'pyvenv.cfg').is_file()),None);"
        "scheme='nt' if sys.platform=='win32' else 'posix_prefix';"
        "paths=sysconfig.get_paths(scheme=scheme,vars={'base':str(venv),'platbase':str(venv)}) if venv else sysconfig.get_paths();"
        "sys.path[:0]=list(dict.fromkeys([paths['purelib'],paths['platlib']]));"
        "from magi_plugin_sdk.runtime import SDK_VERSION,PLUGIN_PROTOCOL_VERSION;"
        "from magi_plugin_sdk.worker import main;"
        "from magi_plugin_sdk.transport import pack,read_frame;"
        "from importlib.metadata import version;"
        "assert SDK_VERSION==sys.argv[1] and PLUGIN_PROTOCOL_VERSION==int(sys.argv[2]);"
        "assert version('magi-plugin-sdk')==SDK_VERSION;"
        "print('Standalone plugin worker identity is verified')"
    )
    subprocess.run([str(executable), "-I", "-S", "-c", probe, sdk_version, str(protocol_version)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument(
        "--sdk", type=Path, default=Path(__file__).resolve().parents[1] / "sdk"
    )
    args = parser.parse_args()
    install_worker_runtime(args.python, args.sdk)


if __name__ == "__main__":
    main()
