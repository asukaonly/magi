#!/usr/bin/env python3
"""Stage the verified ripgrep binary in the release sidecar's native lookup path."""

import hashlib
import io
from pathlib import Path
import sys
import tarfile
import urllib.request
import zipfile

VERSION = "16.0.0"
ASSETS = {
    "aarch64-apple-darwin": (
        "macos-arm64/rg", "tar.gz",
        "5a145656d5067144001bfce6648767fd3254599aa736f1ffdb7fb907760b8ca1",
    ),
    "x86_64-pc-windows-msvc": (
        "windows-x64/rg.exe", "zip",
        "f418ae83e63046a94a7b5f3a44bf3a169f66e689164856ecee02547131c73931",
    ),
}


def main(target: str) -> None:
    destination, suffix, expected = ASSETS[target]
    name = f"ripgrep-{VERSION}-{target}"
    url = f"https://github.com/BurntSushi/ripgrep/releases/download/{VERSION}/{name}.{suffix}"
    with urllib.request.urlopen(url, timeout=90) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != expected:
        raise SystemExit(f"Checksum mismatch for {name}.{suffix}")
    path = Path("runtime/bin/ripgrep") / destination
    member = f"{name}/{path.name}"
    if suffix == "zip":
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            payload = package.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive)) as package:
            payload = package.extractfile(member).read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o755)
    print(f"Staged ripgrep {VERSION} at {path}")


if __name__ == "__main__":
    main(sys.argv[1])
