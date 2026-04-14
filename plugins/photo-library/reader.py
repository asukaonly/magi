"""Read and enumerate local photo files with EXIF metadata extraction."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .file_index import FileIndexCache

IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".tiff", ".tif", ".webp", ".gif", ".bmp",
    ".dng", ".cr2", ".nef", ".arw", ".raw",
})

# Standard EXIF tag IDs
_TAG_IMAGE_DESCRIPTION = 0x010E
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_ORIENTATION = 0x0112
_TAG_DATETIME = 0x0132
_TAG_EXIF_IFD = 0x8769
_TAG_GPS_IFD = 0x8825
# EXIF sub-IFD tags
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_DATETIME_DIGITIZED = 0x9004
_TAG_IMAGE_WIDTH = 0xA002
_TAG_IMAGE_HEIGHT = 0xA003
_TAG_LENS_MODEL = 0xA434
_TAG_FOCAL_LENGTH = 0x920A
_TAG_FNUMBER = 0x829D
_TAG_ISO = 0x8827
_TAG_EXPOSURE_TIME = 0x829A
_TAG_SOFTWARE = 0x0131
_TAG_USER_COMMENT = 0x9286

# GPS tags
_GPS_LATITUDE_REF = 0x0001
_GPS_LATITUDE = 0x0002
_GPS_LONGITUDE_REF = 0x0003
_GPS_LONGITUDE = 0x0004
_GPS_ALTITUDE_REF = 0x0005
_GPS_ALTITUDE = 0x0006

# EXIF type sizes: type_id -> (name, byte_size)
_EXIF_TYPE_SIZES = {
    1: 1,  # BYTE
    2: 1,  # ASCII
    3: 2,  # SHORT
    4: 4,  # LONG
    5: 8,  # RATIONAL
    6: 1,  # SBYTE
    7: 1,  # UNDEFINED
    8: 2,  # SSHORT
    9: 4,  # SLONG
    10: 8,  # SRATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
}


@dataclass
class PhotoMetadata:
    """Extracted metadata from a photo file."""
    path: str = ""
    filename: str = ""
    extension: str = ""
    file_size: int = 0
    file_hash: str = ""
    modified_at: float = 0.0

    # EXIF data
    datetime_original: str = ""
    camera_make: str = ""
    camera_model: str = ""
    lens_model: str = ""
    focal_length: str = ""
    aperture: str = ""
    exposure_time: str = ""
    iso: str = ""
    image_width: int = 0
    image_height: int = 0
    orientation: int = 0

    # GPS
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None

    # Derived
    capture_timestamp: float = 0.0
    image_type: str = "photo"  # photo | screenshot


@dataclass
class ScanResult:
    """Result from scanning a photo directory."""
    items: list[dict[str, Any]] = field(default_factory=list)
    total_scanned: int = 0
    errors: int = 0


def _file_hash_quick(path: Path, chunk_size: int = 65536) -> str:
    """Compute a fast SHA-256 hash reading only the first chunk of the file."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            data = f.read(chunk_size)
            h.update(data)
            # Also include file size for collision resistance
            h.update(str(path.stat().st_size).encode())
    except OSError:
        return ""
    return h.hexdigest()[:16]


def _parse_exif_datetime(dt_str: str) -> float:
    """Parse EXIF datetime string 'YYYY:MM:DD HH:MM:SS' to Unix timestamp."""
    if not dt_str or len(dt_str) < 19:
        return 0.0
    try:
        import calendar
        from time import strptime
        parts = dt_str.strip().rstrip("\x00")
        t = strptime(parts[:19], "%Y:%m:%d %H:%M:%S")
        return float(calendar.timegm(t))
    except (ValueError, OverflowError):
        return 0.0


def _read_rational(data: bytes, offset: int, byte_order: str) -> tuple[int, int]:
    """Read a RATIONAL (two unsigned longs) from EXIF data."""
    fmt = f"{byte_order}II"
    if offset + 8 > len(data):
        return (0, 1)
    num, den = struct.unpack_from(fmt, data, offset)
    return (num, max(den, 1))


def _read_srational(data: bytes, offset: int, byte_order: str) -> tuple[int, int]:
    """Read a SRATIONAL (two signed longs) from EXIF data."""
    fmt = f"{byte_order}ii"
    if offset + 8 > len(data):
        return (0, 1)
    num, den = struct.unpack_from(fmt, data, offset)
    return (num, max(den, 1))


def _gps_dms_to_decimal(dms_rationals: list[tuple[int, int]], ref: str) -> float | None:
    """Convert GPS DMS (degrees/minutes/seconds as rationals) to decimal degrees."""
    if len(dms_rationals) < 3:
        return None
    degrees = dms_rationals[0][0] / dms_rationals[0][1]
    minutes = dms_rationals[1][0] / dms_rationals[1][1]
    seconds = dms_rationals[2][0] / dms_rationals[2][1]
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _read_ifd_entries(
    data: bytes, offset: int, byte_order: str
) -> dict[int, tuple[int, int, int]]:
    """Read IFD entries. Returns {tag_id: (type_id, count, value_offset)}."""
    entries: dict[int, tuple[int, int, int]] = {}
    if offset + 2 > len(data):
        return entries
    fmt_short = f"{byte_order}H"
    fmt_long = f"{byte_order}I"
    num_entries = struct.unpack_from(fmt_short, data, offset)[0]
    pos = offset + 2
    for _ in range(num_entries):
        if pos + 12 > len(data):
            break
        tag_id = struct.unpack_from(fmt_short, data, pos)[0]
        type_id = struct.unpack_from(fmt_short, data, pos + 2)[0]
        count = struct.unpack_from(fmt_long, data, pos + 4)[0]
        # Value or offset: if total size <= 4, value is inline
        type_size = _EXIF_TYPE_SIZES.get(type_id, 1)
        total_size = type_size * count
        if total_size <= 4:
            value_offset = pos + 8  # inline value
        else:
            value_offset = struct.unpack_from(fmt_long, data, pos + 8)[0]
        entries[tag_id] = (type_id, count, value_offset)
        pos += 12
    return entries


def _read_string(data: bytes, offset: int, count: int) -> str:
    """Read a null-terminated ASCII string from EXIF data."""
    end = min(offset + count, len(data))
    raw = data[offset:end]
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _read_short(data: bytes, offset: int, byte_order: str) -> int:
    """Read a SHORT value."""
    if offset + 2 > len(data):
        return 0
    return struct.unpack_from(f"{byte_order}H", data, offset)[0]


# ---------------------------------------------------------------------------
# Screenshot vs photo classification
# ---------------------------------------------------------------------------

# Filename patterns that indicate screenshots
_SCREENSHOT_FILENAME_PATTERNS: tuple[str, ...] = (
    "screenshot",
    "截屏",
    "截图",
    "screen shot",
    "simulator screen shot",
    "cleanshot",
)

# iOS / macOS screen dimensions (logical points × scale, both orientations)
_KNOWN_SCREEN_DIMS: frozenset[tuple[int, int]] = frozenset({
    # iPhone 15 Pro Max / 16 Pro Max
    (1290, 2796), (2796, 1290),
    # iPhone 15 Pro / 16 Pro
    (1179, 2556), (2556, 1179),
    # iPhone 15 / 14
    (1170, 2532), (2532, 1170),
    # iPhone SE 3
    (750, 1334), (1334, 750),
    # iPad Pro 12.9"
    (2048, 2732), (2732, 2048),
    # iPad Pro 11"
    (1668, 2388), (2388, 1668),
    # iPad Air / iPad 10th
    (1640, 2360), (2360, 1640),
    # Common Mac Retina
    (2880, 1800), (1800, 2880),
    (3024, 1964), (1964, 3024),
    (3456, 2234), (2234, 3456),
    (2560, 1600), (1600, 2560),
    (2560, 1664), (1664, 2560),
    (3840, 2160), (2160, 3840),
    (1920, 1080), (1080, 1920),
    (2880, 1920), (1920, 2880),
})


def classify_image_type(item: dict[str, Any]) -> str:
    """Classify an image item as 'photo' or 'screenshot'.

    Uses a weighted heuristic combining filename patterns, EXIF metadata
    presence, software tag, and known screen dimensions.
    """
    score = 0  # positive = screenshot, negative = photo

    filename_lower = str(item.get("filename", "")).lower()

    # Signal 1: filename pattern (strongest signal)
    for pattern in _SCREENSHOT_FILENAME_PATTERNS:
        if pattern in filename_lower:
            score += 3
            break

    # Signal 2: absence of real camera EXIF (no lens, no focal length, no ISO)
    has_lens = bool(item.get("lens_model"))
    has_focal = bool(item.get("focal_length"))
    has_iso = bool(item.get("iso"))
    if not has_lens and not has_focal and not has_iso:
        score += 1

    # Signal 3: Software tag present without camera firmware hint
    software = str(item.get("software", "")).strip()
    if software:
        sw_lower = software.lower()
        # Pure version strings like "16.0" or "17.4.1" are iOS/macOS versions
        # Camera firmware usually contains brand-specific words
        is_os_version = all(
            c in "0123456789. " for c in sw_lower
        ) and "." in sw_lower
        if is_os_version:
            score += 1

    # Signal 4: dimensions match known screen sizes
    w = int(item.get("image_width") or 0)
    h = int(item.get("image_height") or 0)
    if w > 0 and h > 0 and (w, h) in _KNOWN_SCREEN_DIMS:
        score += 1

    # Signal 5: PNG from an Apple device with no camera EXIF is very likely screenshot
    ext = str(item.get("extension", "")).lower()
    make = str(item.get("camera_make", "")).lower()
    if ext == ".png" and make in ("apple", "") and not has_lens:
        score += 1

    # Threshold: 2+ signals ⇒ screenshot
    return "screenshot" if score >= 2 else "photo"


def _read_long(data: bytes, offset: int, byte_order: str) -> int:
    """Read a LONG value."""
    if offset + 4 > len(data):
        return 0
    return struct.unpack_from(f"{byte_order}I", data, offset)[0]


# ---------------------------------------------------------------------------
# HEIC / HEIF ISOBMFF EXIF extraction
# ---------------------------------------------------------------------------

def _extract_heic_exif(f, file_size: int) -> bytes | None:
    """Extract TIFF-format EXIF bytes from an ISOBMFF container (HEIC/HEIF).

    The function parses the box hierarchy looking for Exif data in two
    common locations:
      1. ``meta > iprp > ipco > Exif`` — stored as an item property.
      2. ``meta > iloc`` + ``meta > iinf`` — locate an 'Exif' item type
         and use iloc extents to read its payload.

    Returns raw TIFF EXIF bytes (starting with ``II`` or ``MM``) or *None*.
    """
    f.seek(0)

    def _read_box_header(pos: int) -> tuple[int, bytes, int, int] | None:
        """Read an ISOBMFF box header at *pos*.

        Returns ``(box_size, box_type, header_size, data_start)`` or
        *None* if the header cannot be read.
        """
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return None
        size = struct.unpack(">I", hdr[:4])[0]
        box_type = hdr[4:8]
        header_size = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return None
            size = struct.unpack(">Q", ext)[0]
            header_size = 16
        elif size == 0:
            size = file_size - pos
        return size, box_type, header_size, pos + header_size

    def _iter_boxes(start: int, end: int):
        """Yield ``(box_type, data_start, data_end)`` for top-level boxes in ``[start, end)``."""
        pos = start
        while pos < end:
            info = _read_box_header(pos)
            if info is None or info[0] <= 0:
                break
            box_size, box_type, hdr_size, data_start = info
            box_end = pos + box_size
            yield box_type, data_start, min(box_end, end)
            pos = box_end

    def _find_box(start: int, end: int, target: bytes) -> tuple[int, int] | None:
        for btype, dstart, dend in _iter_boxes(start, end):
            if btype == target:
                return dstart, dend
        return None

    def _find_exif_in_ipco(ipco_start: int, ipco_end: int) -> bytes | None:
        """Look for an 'Exif' property box inside ipco."""
        for btype, dstart, dend in _iter_boxes(ipco_start, ipco_end):
            if btype == b"Exif":
                f.seek(dstart)
                payload = f.read(dend - dstart)
                if len(payload) < 4:
                    continue
                # First 4 bytes: TIFF header offset (usually 0 or 6)
                tiff_offset = struct.unpack(">I", payload[:4])[0]
                raw = payload[4 + tiff_offset:]
                if len(raw) >= 8 and raw[:2] in (b"II", b"MM"):
                    return raw
        return None

    try:
        # Step 1: find the 'meta' box at top level
        meta = _find_box(0, file_size, b"meta")
        if meta is None:
            return None
        meta_start, meta_end = meta
        # meta is a FullBox — skip version(1) + flags(3)
        meta_inner = meta_start + 4

        # Step 2: look for iprp > ipco > Exif
        iprp = _find_box(meta_inner, meta_end, b"iprp")
        if iprp is not None:
            iprp_start, iprp_end = iprp
            ipco = _find_box(iprp_start, iprp_end, b"ipco")
            if ipco is not None:
                result = _find_exif_in_ipco(*ipco)
                if result is not None:
                    return result

        # Step 3: fallback — scan all boxes inside meta for an inlined Exif box
        for btype, dstart, dend in _iter_boxes(meta_inner, meta_end):
            if btype == b"Exif":
                f.seek(dstart)
                payload = f.read(dend - dstart)
                if len(payload) < 4:
                    continue
                tiff_offset = struct.unpack(">I", payload[:4])[0]
                raw = payload[4 + tiff_offset:]
                if len(raw) >= 8 and raw[:2] in (b"II", b"MM"):
                    return raw

    except (OSError, struct.error):
        pass
    return None


def extract_exif(path: Path) -> dict[str, Any]:
    """Extract EXIF metadata from a JPEG/TIFF file using pure Python.

    Returns a dict with extracted fields. Returns empty dict on failure.
    """
    result: dict[str, Any] = {}
    try:
        with path.open("rb") as f:
            header = f.read(12)
            if len(header) < 4:
                return result

            exif_data: bytes | None = None

            # JPEG: look for APP1 marker with Exif header
            if header[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0:1] != b"\xff":
                        break
                    length_bytes = f.read(2)
                    if len(length_bytes) < 2:
                        break
                    length = struct.unpack(">H", length_bytes)[0]
                    if marker == b"\xff\xe1":  # APP1
                        seg = f.read(length - 2)
                        if seg[:6] == b"Exif\x00\x00":
                            exif_data = seg[6:]
                            break
                    else:
                        f.seek(length - 2, 1)

            # TIFF: direct IFD access
            elif header[:2] in (b"II", b"MM"):
                f.seek(0)
                exif_data = f.read(min(path.stat().st_size, 256 * 1024))

            # HEIC / HEIF: ISOBMFF container with embedded EXIF
            elif len(header) >= 8 and header[4:8] == b"ftyp":
                exif_data = _extract_heic_exif(f, path.stat().st_size)

            if not exif_data or len(exif_data) < 8:
                return result

            # Determine byte order
            if exif_data[:2] == b"II":
                byte_order = "<"
            elif exif_data[:2] == b"MM":
                byte_order = ">"
            else:
                return result

            # Read IFD0 offset
            ifd0_offset = struct.unpack_from(f"{byte_order}I", exif_data, 4)[0]
            ifd0 = _read_ifd_entries(exif_data, ifd0_offset, byte_order)

            # IFD0 tags
            if _TAG_MAKE in ifd0:
                _, count, off = ifd0[_TAG_MAKE]
                result["camera_make"] = _read_string(exif_data, off, count)
            if _TAG_MODEL in ifd0:
                _, count, off = ifd0[_TAG_MODEL]
                result["camera_model"] = _read_string(exif_data, off, count)
            if _TAG_ORIENTATION in ifd0:
                _, _, off = ifd0[_TAG_ORIENTATION]
                result["orientation"] = _read_short(exif_data, off, byte_order)
            if _TAG_DATETIME in ifd0:
                _, count, off = ifd0[_TAG_DATETIME]
                result["datetime"] = _read_string(exif_data, off, count)
            if _TAG_SOFTWARE in ifd0:
                _, count, off = ifd0[_TAG_SOFTWARE]
                result["software"] = _read_string(exif_data, off, count)

            # EXIF sub-IFD
            if _TAG_EXIF_IFD in ifd0:
                _, _, off = ifd0[_TAG_EXIF_IFD]
                exif_offset = _read_long(exif_data, off, byte_order)
                exif_ifd = _read_ifd_entries(exif_data, exif_offset, byte_order)

                if _TAG_DATETIME_ORIGINAL in exif_ifd:
                    _, count, off = exif_ifd[_TAG_DATETIME_ORIGINAL]
                    result["datetime_original"] = _read_string(exif_data, off, count)
                if _TAG_IMAGE_WIDTH in exif_ifd:
                    type_id, _, off = exif_ifd[_TAG_IMAGE_WIDTH]
                    if type_id == 3:
                        result["image_width"] = _read_short(exif_data, off, byte_order)
                    else:
                        result["image_width"] = _read_long(exif_data, off, byte_order)
                if _TAG_IMAGE_HEIGHT in exif_ifd:
                    type_id, _, off = exif_ifd[_TAG_IMAGE_HEIGHT]
                    if type_id == 3:
                        result["image_height"] = _read_short(exif_data, off, byte_order)
                    else:
                        result["image_height"] = _read_long(exif_data, off, byte_order)
                if _TAG_LENS_MODEL in exif_ifd:
                    _, count, off = exif_ifd[_TAG_LENS_MODEL]
                    result["lens_model"] = _read_string(exif_data, off, count)
                if _TAG_FOCAL_LENGTH in exif_ifd:
                    _, _, off = exif_ifd[_TAG_FOCAL_LENGTH]
                    num, den = _read_rational(exif_data, off, byte_order)
                    result["focal_length"] = f"{num / den:.1f}mm"
                if _TAG_FNUMBER in exif_ifd:
                    _, _, off = exif_ifd[_TAG_FNUMBER]
                    num, den = _read_rational(exif_data, off, byte_order)
                    result["aperture"] = f"f/{num / den:.1f}"
                if _TAG_EXPOSURE_TIME in exif_ifd:
                    _, _, off = exif_ifd[_TAG_EXPOSURE_TIME]
                    num, den = _read_rational(exif_data, off, byte_order)
                    if num > 0 and den > 0:
                        if num < den:
                            result["exposure_time"] = f"1/{den // num}s"
                        else:
                            result["exposure_time"] = f"{num / den:.1f}s"
                if _TAG_ISO in exif_ifd:
                    _, _, off = exif_ifd[_TAG_ISO]
                    result["iso"] = str(_read_short(exif_data, off, byte_order))

            # GPS IFD
            if _TAG_GPS_IFD in ifd0:
                _, _, off = ifd0[_TAG_GPS_IFD]
                gps_offset = _read_long(exif_data, off, byte_order)
                gps_ifd = _read_ifd_entries(exif_data, gps_offset, byte_order)

                lat_ref = ""
                lon_ref = ""
                lat_dms: list[tuple[int, int]] = []
                lon_dms: list[tuple[int, int]] = []

                if _GPS_LATITUDE_REF in gps_ifd:
                    _, count, off = gps_ifd[_GPS_LATITUDE_REF]
                    lat_ref = _read_string(exif_data, off, count)
                if _GPS_LATITUDE in gps_ifd:
                    _, _, off = gps_ifd[_GPS_LATITUDE]
                    lat_dms = [
                        _read_rational(exif_data, off + i * 8, byte_order)
                        for i in range(3)
                    ]
                if _GPS_LONGITUDE_REF in gps_ifd:
                    _, count, off = gps_ifd[_GPS_LONGITUDE_REF]
                    lon_ref = _read_string(exif_data, off, count)
                if _GPS_LONGITUDE in gps_ifd:
                    _, _, off = gps_ifd[_GPS_LONGITUDE]
                    lon_dms = [
                        _read_rational(exif_data, off + i * 8, byte_order)
                        for i in range(3)
                    ]
                if lat_dms and lat_ref:
                    result["latitude"] = _gps_dms_to_decimal(lat_dms, lat_ref)
                if lon_dms and lon_ref:
                    result["longitude"] = _gps_dms_to_decimal(lon_dms, lon_ref)
                if _GPS_ALTITUDE in gps_ifd:
                    _, _, off = gps_ifd[_GPS_ALTITUDE]
                    num, den = _read_rational(exif_data, off, byte_order)
                    alt = num / den
                    if _GPS_ALTITUDE_REF in gps_ifd:
                        _, _, ref_off = gps_ifd[_GPS_ALTITUDE_REF]
                        if exif_data[ref_off:ref_off + 1] == b"\x01":
                            alt = -alt
                    result["altitude"] = alt

    except (OSError, struct.error):
        pass
    return result


def _matches_any_pattern(rel_path: str, patterns: list[str]) -> bool:
    """Check whether *rel_path* matches any of the glob *patterns*."""
    normalized = rel_path.replace(os.sep, "/")
    for pat in patterns:
        if fnmatch.fnmatch(normalized, pat):
            return True
    return False


class PhotoLibraryReader:
    """Scan a local directory for image files and extract EXIF metadata."""

    def __init__(
        self,
        *,
        extensions: frozenset[str] | None = None,
        file_index: "FileIndexCache | None" = None,
    ) -> None:
        self.extensions = extensions or IMAGE_EXTENSIONS
        self._file_index = file_index

    def scan_directory(
        self,
        source_path: str,
        *,
        limit: int = 500,
        min_modified_at: float = 0.0,
        exclude_patterns: list[str] | None = None,
        analysis_features: list[str] | None = None,
    ) -> ScanResult:
        """Scan *source_path* for image files modified after *min_modified_at*.

        *exclude_patterns* is a list of glob patterns (matched against the
        path relative to *source_path*).  Directories whose relative path
        matches any pattern are pruned in-place so their subtree is skipped
        entirely.

        Returns a :class:`ScanResult` with normalized item dicts suitable for
        the sensor's ``collect_items`` pipeline.
        """
        root = Path(source_path).expanduser().resolve()
        if not root.is_dir():
            return ScanResult()

        compiled_excludes = exclude_patterns or []
        do_exif = analysis_features is None or "exif" in analysis_features

        items: list[dict[str, Any]] = []
        cache_entries: list[tuple[str, float, int, str, dict[str, Any], float]] = []
        now = time.time()
        total = 0
        errors = 0

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excluded directories in-place so os.walk skips them
            if compiled_excludes:
                rel_dir = os.path.relpath(dirpath, root)
                dirnames[:] = [
                    d for d in dirnames
                    if not _matches_any_pattern(
                        os.path.join(rel_dir, d) if rel_dir != "." else d,
                        compiled_excludes,
                    )
                ]

            for name in filenames:
                ext = Path(name).suffix.lower()
                if ext not in self.extensions:
                    continue
                total += 1
                filepath = Path(dirpath) / name
                try:
                    stat = filepath.stat()
                    mtime = stat.st_mtime
                    if mtime <= min_modified_at:
                        continue
                    fpath_str = str(filepath)

                    # Try file index cache first
                    cached_exif: dict[str, Any] | None = None
                    if do_exif and self._file_index is not None:
                        cached_exif = self._file_index.get(fpath_str, mtime, stat.st_size)

                    fhash = _file_hash_quick(filepath)

                    if cached_exif is not None:
                        exif = cached_exif
                    elif do_exif:
                        exif = extract_exif(filepath)
                        # Write-through to cache
                        if self._file_index is not None:
                            cache_entries.append((fpath_str, mtime, stat.st_size, fhash, exif, now))
                    else:
                        exif = {}

                    capture_ts = _parse_exif_datetime(
                        exif.get("datetime_original") or exif.get("datetime") or ""
                    )
                    item: dict[str, Any] = {
                        "asset_local_id": fhash or f"file:{name}",
                        "path": fpath_str,
                        "filename": name,
                        "extension": ext,
                        "file_size": stat.st_size,
                        "file_hash": fhash,
                        "modified_at": mtime,
                        "capture_timestamp": capture_ts or mtime,
                        "datetime_original": exif.get("datetime_original", ""),
                        "camera_make": exif.get("camera_make", ""),
                        "camera_model": exif.get("camera_model", ""),
                        "lens_model": exif.get("lens_model", ""),
                        "focal_length": exif.get("focal_length", ""),
                        "aperture": exif.get("aperture", ""),
                        "exposure_time": exif.get("exposure_time", ""),
                        "iso": exif.get("iso", ""),
                        "image_width": exif.get("image_width", 0),
                        "image_height": exif.get("image_height", 0),
                        "orientation": exif.get("orientation", 0),
                        "latitude": exif.get("latitude"),
                        "longitude": exif.get("longitude"),
                        "altitude": exif.get("altitude"),
                        "software": exif.get("software", ""),
                    }
                    item["image_type"] = classify_image_type(item)
                    items.append(item)
                    if len(items) >= limit:
                        break
                except OSError:
                    errors += 1
            else:
                # Inner loop completed without break — continue to next directory
                continue
            # Inner loop was broken (limit reached) — flush cache and return
            if cache_entries and self._file_index is not None:
                self._file_index.put_batch(cache_entries)
            return ScanResult(items=items, total_scanned=total, errors=errors)

        # Flush any remaining cache entries
        if cache_entries and self._file_index is not None:
            self._file_index.put_batch(cache_entries)

        return ScanResult(items=items, total_scanned=total, errors=errors)
