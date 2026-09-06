#!/usr/bin/env python3
"""Install and validate the standalone SDK in staged desktop plugin Python."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def install_worker_runtime(executable: Path, sdk_directory: Path) -> None:
    """Install a wheel-backed SDK; editable imports cannot work in a bundle."""
    executable = executable.absolute()
    sdk_directory = sdk_directory.resolve(strict=True)
    if not (sdk_directory / "pyproject.toml").is_file():
        raise ValueError("Worker SDK directory must contain pyproject.toml")
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
        "paths=sysconfig.get_paths(vars={'base':str(venv),'platbase':str(venv)}) if venv else sysconfig.get_paths();"
        "sys.path[:0]=list(dict.fromkeys([paths['purelib'],paths['platlib']]));"
        "from magi_plugin_sdk.runtime import SDK_VERSION,PLUGIN_PROTOCOL_VERSION;"
        "from magi_plugin_sdk.worker import main;"
        "from magi_plugin_sdk.transport import pack,read_frame;"
        "assert SDK_VERSION=='0.2.0' and PLUGIN_PROTOCOL_VERSION==2;"
        "print('Standalone plugin worker protocol 2 is ready')"
    )
    subprocess.run([str(executable), "-I", "-S", "-c", probe], check=True)


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
