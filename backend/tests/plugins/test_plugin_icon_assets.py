from __future__ import annotations

import base64
from pathlib import Path

import pytest

from magi.plugins.discovery import load_plugin_manifest
from magi.plugins.icon_assets import (
    MAX_ICON_BYTES,
    encode_plugin_icon_asset,
    resolve_plugin_icon,
    sanitize_inline_icon,
    sanitize_lucide_icon,
    sanitize_registry_icon,
)

SAFE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M1 1h2v2H1z"/></svg>'
)


def _write_manifest(plugin_dir: Path, icon: str) -> Path:
    manifest_path = plugin_dir / "plugin.toml"
    manifest_path.write_text(
        "\n".join(
            [
                "[plugin]",
                'protocol_version = 2',
                'min_sdk_version = "0.2.0"',
                'execution_mode = "trusted_process"',
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
    ("mime_type", "data"),
    [
        ("image/svg+xml", SAFE_SVG),
        ("image/png", b"\x89PNG\r\n\x1a\npayload"),
        ("image/webp", b"RIFF\x04\x00\x00\x00WEBPpayload"),
    ],
)
def test_accepts_safe_registry_inline_icons(mime_type: str, data: bytes) -> None:
    icon = f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"

    assert sanitize_inline_icon(icon) == icon


@pytest.mark.parametrize(
    "icon",
    [
        "data:image/png;base64,not valid base64",
        "data:text/html;base64,PGgxPmhpPC9oMT4=",
        "data:image/png;base64,PHN2Zy8+",
        "data:image/webp;base64,PHN2Zy8+",
        "data:image/svg+xml;base64,"
        + base64.b64encode(b"<svg><script>alert(1)</script></svg>").decode("ascii"),
        "data:image/png;base64,"
        + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_ICON_BYTES).decode("ascii"),
    ],
)
def test_rejects_untrusted_registry_inline_icons(icon: str) -> None:
    assert sanitize_inline_icon(icon) == ""


@pytest.mark.parametrize(
    "icon",
    [
        "lucide:calendar-days",
        "lucide:gamepad-2",
    ],
)
def test_accepts_bounded_lucide_registry_icons(icon: str) -> None:
    assert sanitize_lucide_icon(icon) == icon


@pytest.mark.parametrize(
    "icon",
    [
        "brand:calendar",
        "lucide:Calendar",
        "lucide:calendar_days",
        "lucide:../calendar",
        f"lucide:{'x' * 65}",
    ],
)
def test_rejects_invalid_registry_icon_references(icon: str) -> None:
    assert sanitize_lucide_icon(icon) == ""


def test_registry_icon_falls_back_to_safe_lucide_reference() -> None:
    assert (
        sanitize_registry_icon(
            "data:image/png;base64,PHN2Zy8+",
            "lucide:calendar-days",
        )
        == "lucide:calendar-days"
    )


@pytest.mark.parametrize(
    "unsafe_inline",
    [
        "data:image/png;base64,not-valid-base64",
        "data:image/png;base64,PHN2Zy8+",
        "data:image/webp;base64,PHN2Zy8+",
        "data:image/svg+xml;base64,"
        + base64.b64encode(b"<svg><script>alert(1)</script></svg>").decode("ascii"),
        "data:image/png;base64,"
        + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_ICON_BYTES).decode("ascii"),
    ],
)
def test_every_unsafe_inline_registry_icon_uses_lucide_fallback(
    unsafe_inline: str,
) -> None:
    assert sanitize_registry_icon(unsafe_inline, "lucide:shield") == "lucide:shield"


def test_registry_icon_accepts_safe_inline_fallback_field() -> None:
    fallback = "data:image/svg+xml;base64," + base64.b64encode(SAFE_SVG).decode("ascii")

    assert sanitize_registry_icon("", fallback) == fallback


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
