from __future__ import annotations

import base64
from pathlib import Path

import pytest

from magi.plugins.discovery import load_plugin_manifest
from magi.plugins.icon_assets import MAX_ICON_BYTES, encode_plugin_icon_asset, resolve_plugin_icon


SAFE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M1 1h2v2H1z"/></svg>'
)


def _write_manifest(plugin_dir: Path, icon: str) -> Path:
    manifest_path = plugin_dir / "plugin.toml"
    manifest_path.write_text(
        "\n".join(
            [
                "[plugin]",
                'id = "example"',
                'name = "Example"',
                'version = "0.1.0"',
                f'icon = "{icon}"',
            ]
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_encodes_safe_svg_asset(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "icon.svg").write_bytes(SAFE_SVG)

    result = encode_plugin_icon_asset("asset:assets/icon.svg", tmp_path)

    assert result is not None
    prefix, encoded = result.split(",", 1)
    assert prefix == "data:image/svg+xml;base64"
    assert base64.b64decode(encoded) == SAFE_SVG


def test_preserves_lucide_icon_reference(tmp_path: Path) -> None:
    assert resolve_plugin_icon("lucide:calendar-days", tmp_path) == "lucide:calendar-days"


@pytest.mark.parametrize(
    "icon",
    [
        "asset:../icon.svg",
        "asset:/tmp/icon.svg",
        "asset:",
    ],
)
def test_rejects_icon_paths_outside_package(tmp_path: Path, icon: str) -> None:
    with pytest.raises(ValueError):
        encode_plugin_icon_asset(icon, tmp_path)


def test_rejects_unsafe_svg(tmp_path: Path) -> None:
    icon_path = tmp_path / "icon.svg"
    icon_path.write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden <script>"):
        encode_plugin_icon_asset("asset:icon.svg", tmp_path)


def test_rejects_symlinked_icon(tmp_path: Path) -> None:
    target = tmp_path / "target.svg"
    target.write_bytes(SAFE_SVG)
    (tmp_path / "icon.svg").symlink_to(target)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        encode_plugin_icon_asset("asset:icon.svg", tmp_path)


def test_rejects_oversized_icon(tmp_path: Path) -> None:
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_ICON_BYTES)

    with pytest.raises(ValueError, match="must be between"):
        encode_plugin_icon_asset("asset:icon.png", tmp_path)


def test_manifest_discovery_validates_local_icon(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "icon.svg").write_bytes(SAFE_SVG)
    manifest_path = _write_manifest(tmp_path, "asset:assets/icon.svg")

    manifest = load_plugin_manifest(manifest_path, source="external")

    assert manifest.icon == "asset:assets/icon.svg"


def test_manifest_discovery_rejects_missing_icon(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, "asset:assets/missing.svg")

    with pytest.raises(ValueError, match="does not exist"):
        load_plugin_manifest(manifest_path, source="external")
