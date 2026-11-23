"""Validate uploaded release assets and the two signed updater entries."""

import json
import sys
from pathlib import Path


def check_release_assets(directory: Path, repository: str, tag: str) -> None:
    version = tag.removeprefix("v")
    windows = f"Magi_{version}_x64-setup.exe"
    macos = "Magi_aarch64.app.tar.gz"
    service = f"MagiServer_{version}_aarch64-apple-darwin.dmg"
    required = {
        f"Magi_{version}_aarch64.dmg", windows, macos, f"{windows}.sig", f"{macos}.sig",
        service, f"{service}.sha256", f"{service}.json", "latest.json",
    }
    assets = json.loads((directory / "assets.json").read_text())["assets"]
    uploaded = {a["name"] for a in assets if a["state"] == "uploaded" and a["size"] > 0}
    if missing := required - uploaded:
        raise ValueError(f"Missing release assets: {', '.join(sorted(missing))}")

    feed = json.loads((directory / "latest.json").read_text())
    if feed["version"] != version:
        raise ValueError(f"Updater version does not match {tag}")
    for platform, bundle in {"windows-x86_64": windows, "darwin-aarch64": macos}.items():
        entry = feed["platforms"][platform]
        url = f"https://github.com/{repository}/releases/download/{tag}/{bundle}"
        signature = (directory / f"{bundle}.sig").read_text().strip()
        if entry["url"] != url or not signature or entry["signature"].strip() != signature:
            raise ValueError(f"Updater URL or signature mismatch for {platform}")


if __name__ == "__main__":
    check_release_assets(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
