"""Safe loading for plugin-owned icon assets."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path, PurePosixPath
import re
from xml.etree import ElementTree

ASSET_ICON_PREFIX = "asset:"
MAX_ICON_BYTES = 64 * 1024
ICON_MIME_TYPES = {
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
FORBIDDEN_SVG_ELEMENTS = {
    "audio",
    "embed",
    "foreignobject",
    "iframe",
    "image",
    "object",
    "script",
    "style",
    "use",
    "video",
}
LUCIDE_ICON_RE = re.compile(r"lucide:([a-z0-9]+(?:-[a-z0-9]+)*)")
INLINE_ICON_RE = re.compile(
    r"data:(image/(?:png|webp)|image/svg\+xml);base64,([A-Za-z0-9+/]+={0,2})"
)


def _asset_icon_path(plugin_dir: Path, icon: str) -> Path | None:
    if not icon.startswith(ASSET_ICON_PREFIX):
        return None
    raw_path = icon.removeprefix(ASSET_ICON_PREFIX).strip()
    relative = PurePosixPath(raw_path)
    if (
        not raw_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"Invalid plugin icon asset path: {icon}")
    root = plugin_dir.resolve()
    candidate = plugin_dir / Path(*relative.parts)
    if candidate.is_symlink():
        raise ValueError(f"Plugin icon asset cannot be a symlink: {icon}")
    path = candidate.resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Plugin icon asset escapes package directory: {icon}")
    return path


def _validate_svg_icon(data: bytes, *, path: Path) -> None:
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError(f"Plugin icon SVG cannot declare entities: {path}")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(f"Plugin icon SVG is invalid: {path}") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValueError(f"Plugin icon SVG must have an <svg> root: {path}")
    for element in root.iter():
        element_name = element.tag.rsplit("}", 1)[-1].lower()
        if element_name in FORBIDDEN_SVG_ELEMENTS:
            raise ValueError(f"Plugin icon SVG contains forbidden <{element_name}> element: {path}")
        for raw_name, raw_value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].lower()
            value = str(raw_value).strip().lower()
            if (
                name.startswith("on")
                or name in {"href", "src", "style"}
                or "url(" in value
                or value.startswith(("data:", "http:", "https:", "//"))
            ):
                raise ValueError(f"Plugin icon SVG contains forbidden attribute {name}: {path}")


def encode_plugin_icon_asset(icon: str, plugin_dir: Path) -> str | None:
    """Return a validated package icon as a self-contained data URI."""
    path = _asset_icon_path(plugin_dir, icon)
    if path is None:
        return None
    if not path.is_file():
        raise ValueError(f"Plugin icon asset does not exist: {path}")
    suffix = path.suffix.lower()
    mime_type = ICON_MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError(f"Unsupported plugin icon format: {path}")
    data = path.read_bytes()
    if not data or len(data) > MAX_ICON_BYTES:
        raise ValueError(f"Plugin icon must be between 1 and {MAX_ICON_BYTES} bytes: {path}")
    if suffix == ".svg":
        _validate_svg_icon(data, path=path)
    elif suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Plugin icon is not a valid PNG: {path}")
    elif suffix == ".webp" and not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        raise ValueError(f"Plugin icon is not a valid WebP image: {path}")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def resolve_plugin_icon(icon: str, plugin_dir: str | Path) -> str:
    """Resolve an asset reference while preserving library icon ids."""
    encoded = encode_plugin_icon_asset(icon, Path(plugin_dir))
    return encoded if encoded is not None else icon


def sanitize_inline_icon(icon: str) -> str:
    """Return a safe registry-provided data icon or an empty string."""

    if not isinstance(icon, str) or len(icon) > (MAX_ICON_BYTES * 2):
        return ""
    match = INLINE_ICON_RE.fullmatch(icon)
    if match is None:
        return ""
    mime_type, encoded = match.groups()
    if len(encoded) > ((MAX_ICON_BYTES + 2) // 3) * 4:
        return ""
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return ""
    if not data or len(data) > MAX_ICON_BYTES or base64.b64encode(data).decode("ascii") != encoded:
        return ""
    try:
        if mime_type == "image/svg+xml":
            _validate_svg_icon(data, path=Path("registry-inline-icon.svg"))
        elif mime_type == "image/png":
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                return ""
        elif not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
            return ""
    except ValueError:
        return ""
    return icon


def sanitize_lucide_icon(icon: str) -> str:
    """Return a bounded Lucide reference or an empty string."""

    if not isinstance(icon, str):
        return ""
    match = LUCIDE_ICON_RE.fullmatch(icon)
    if match is None or len(match.group(1)) > 64:
        return ""
    return icon


def sanitize_registry_icon(icon_data: str, fallback: str = "") -> str:
    """Prefer a safe inline icon, then a bounded Lucide fallback."""

    return (
        sanitize_inline_icon(icon_data)
        or sanitize_inline_icon(fallback)
        or sanitize_lucide_icon(fallback)
    )


__all__ = [
    "ASSET_ICON_PREFIX",
    "MAX_ICON_BYTES",
    "encode_plugin_icon_asset",
    "resolve_plugin_icon",
    "sanitize_inline_icon",
    "sanitize_lucide_icon",
    "sanitize_registry_icon",
]
