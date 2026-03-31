"""Tests for photo library reader — directory scanning and EXIF extraction helpers."""
from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

import pytest

# photo-library has a hyphen, so we must load via importlib
_plugin_dir = Path(__file__).resolve().parents[3] / "plugins" / "photo-library"

def _load_module(name: str):
    path = _plugin_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"photo_library_{name}", path,
        submodule_search_locations=[str(_plugin_dir)],
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

_reader_mod = _load_module("reader")
IMAGE_EXTENSIONS = _reader_mod.IMAGE_EXTENSIONS
PhotoLibraryReader = _reader_mod.PhotoLibraryReader
ScanResult = _reader_mod.ScanResult
_file_hash_quick = _reader_mod._file_hash_quick
_gps_dms_to_decimal = _reader_mod._gps_dms_to_decimal
_parse_exif_datetime = _reader_mod._parse_exif_datetime
extract_exif = _reader_mod.extract_exif
classify_image_type = _reader_mod.classify_image_type


# ---------------------------------------------------------------------------
# _parse_exif_datetime
# ---------------------------------------------------------------------------

class TestParseExifDatetime:
    def test_valid_datetime(self):
        ts = _parse_exif_datetime("2024:06:15 14:30:00")
        assert ts > 0
        # 2024-06-15 14:30:00 UTC
        assert abs(ts - 1718461800.0) < 2

    def test_empty_string(self):
        assert _parse_exif_datetime("") == 0.0

    def test_short_string(self):
        assert _parse_exif_datetime("2024:06") == 0.0

    def test_null_terminated(self):
        ts = _parse_exif_datetime("2024:06:15 14:30:00\x00")
        assert ts > 0

    def test_invalid_format(self):
        assert _parse_exif_datetime("not-a-date-string!!") == 0.0


# ---------------------------------------------------------------------------
# _gps_dms_to_decimal
# ---------------------------------------------------------------------------

class TestGpsDmsToDecimal:
    def test_north_east(self):
        # 35°39'31" N -> ~35.6586
        dms = [(35, 1), (39, 1), (31, 1)]
        result = _gps_dms_to_decimal(dms, "N")
        assert result is not None
        assert abs(result - 35.6586) < 0.001

    def test_south(self):
        dms = [(33, 1), (51, 1), (54, 1)]
        result = _gps_dms_to_decimal(dms, "S")
        assert result is not None
        assert result < 0

    def test_west(self):
        dms = [(118, 1), (14, 1), (34, 1)]
        result = _gps_dms_to_decimal(dms, "W")
        assert result is not None
        assert result < 0

    def test_too_few_entries(self):
        assert _gps_dms_to_decimal([(35, 1)], "N") is None


# ---------------------------------------------------------------------------
# _file_hash_quick
# ---------------------------------------------------------------------------

class TestFileHashQuick:
    def test_returns_hex_string(self, tmp_path: Path):
        f = tmp_path / "test.jpg"
        f.write_bytes(b"\xff" * 1024)
        h = _file_hash_quick(f)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_nonexistent_file(self, tmp_path: Path):
        assert _file_hash_quick(tmp_path / "nope.jpg") == ""

    def test_different_content_different_hash(self, tmp_path: Path):
        a = tmp_path / "a.jpg"
        b = tmp_path / "b.jpg"
        a.write_bytes(b"\x00" * 100)
        b.write_bytes(b"\xff" * 100)
        assert _file_hash_quick(a) != _file_hash_quick(b)


# ---------------------------------------------------------------------------
# extract_exif — with a minimal synthetic JPEG
# ---------------------------------------------------------------------------

def _build_minimal_jpeg_with_exif(
    *,
    make: str = "",
    model: str = "",
    datetime_original: str = "",
) -> bytes:
    """Build a minimal JPEG file with an Exif APP1 segment."""
    byte_order = b"MM"  # big-endian
    bo = ">"

    # Build IFD0 entries
    ifd_entries: list[bytes] = []
    data_area = bytearray()
    # IFD0 starts at offset 8; we'll compute data_area offset after entries
    tag_list: list[tuple[int, str, int]] = []  # (tag_id, value, type_id)

    def add_string_tag(tag_id: int, value: str) -> None:
        if not value:
            return
        val_bytes = value.encode("ascii") + b"\x00"
        tag_list.append((tag_id, value, 2))

    add_string_tag(0x010F, make)
    add_string_tag(0x0110, model)

    num_entries = len(tag_list)
    # IFD0 offset = 8
    # IFD0 size = 2 (count) + 12*num_entries + 4 (next IFD pointer)
    ifd0_size = 2 + 12 * num_entries + 4
    data_offset = 8 + ifd0_size

    ifd0 = bytearray()
    ifd0 += struct.pack(f"{bo}H", num_entries)
    for tag_id, value, type_id in tag_list:
        val_bytes = value.encode("ascii") + b"\x00"
        count = len(val_bytes)
        if count <= 4:
            # Inline
            padded = val_bytes.ljust(4, b"\x00")
            ifd0 += struct.pack(f"{bo}HHI", tag_id, type_id, count)
            ifd0 += padded
        else:
            ifd0 += struct.pack(f"{bo}HHII", tag_id, type_id, count, data_offset + len(data_area))
            data_area += val_bytes

    ifd0 += struct.pack(f"{bo}I", 0)  # next IFD = 0

    # TIFF header
    tiff = byte_order + b"\x00\x2a" + struct.pack(f"{bo}I", 8) + bytes(ifd0) + bytes(data_area)

    # Exif APP1 segment
    exif_header = b"Exif\x00\x00"
    app1_payload = exif_header + tiff
    app1_length = len(app1_payload) + 2
    app1 = b"\xff\xe1" + struct.pack(">H", app1_length) + app1_payload

    # Minimal JPEG: SOI + APP1 + EOI
    return b"\xff\xd8" + app1 + b"\xff\xd9"


class TestExtractExif:
    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.jpg"
        f.write_bytes(b"")
        assert extract_exif(f) == {}

    def test_not_jpeg(self, tmp_path: Path):
        f = tmp_path / "text.txt"
        f.write_bytes(b"Hello world, this is not an image")
        assert extract_exif(f) == {}

    def test_minimal_jpeg_with_make_model(self, tmp_path: Path):
        data = _build_minimal_jpeg_with_exif(make="Canon", model="EOS R5")
        f = tmp_path / "canon.jpg"
        f.write_bytes(data)
        exif = extract_exif(f)
        assert exif.get("camera_make") == "Canon"
        assert exif.get("camera_model") == "EOS R5"

    def test_nonexistent_file(self, tmp_path: Path):
        assert extract_exif(tmp_path / "missing.jpg") == {}


# ---------------------------------------------------------------------------
# PhotoLibraryReader.scan_directory
# ---------------------------------------------------------------------------

class TestScanDirectory:
    def _make_fake_images(self, directory: Path, count: int = 3, ext: str = ".jpg") -> list[Path]:
        """Create fake image files (non-JPEG content, EXIF won't parse but scan should still work)."""
        paths = []
        for i in range(count):
            f = directory / f"img_{i:03d}{ext}"
            f.write_bytes(b"\x00" * 100)
            paths.append(f)
        return paths

    def test_scan_empty_directory(self, tmp_path: Path):
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        assert isinstance(result, ScanResult)
        assert result.items == []
        assert result.total_scanned == 0

    def test_scan_nonexistent_directory(self):
        reader = PhotoLibraryReader()
        result = reader.scan_directory("/nonexistent/path/12345")
        assert result.items == []

    def test_scan_finds_image_files(self, tmp_path: Path):
        self._make_fake_images(tmp_path, count=3)
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        assert len(result.items) == 3
        assert result.total_scanned == 3
        for item in result.items:
            assert item["extension"] == ".jpg"
            assert item["filename"].endswith(".jpg")
            assert item["file_hash"] != ""

    def test_scan_respects_limit(self, tmp_path: Path):
        self._make_fake_images(tmp_path, count=10)
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path), limit=3)
        assert len(result.items) == 3

    def test_scan_respects_min_modified_at(self, tmp_path: Path):
        import time
        paths = self._make_fake_images(tmp_path, count=3)
        now = time.time()
        # All files have mtime ~ now, so a future threshold excludes all
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path), min_modified_at=now + 100)
        assert len(result.items) == 0

    def test_scan_ignores_non_image_extensions(self, tmp_path: Path):
        (tmp_path / "readme.txt").write_text("text")
        (tmp_path / "data.csv").write_text("a,b,c")
        self._make_fake_images(tmp_path, count=1)
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        assert len(result.items) == 1

    def test_scan_recurses_subdirectories(self, tmp_path: Path):
        sub = tmp_path / "2024" / "June"
        sub.mkdir(parents=True)
        self._make_fake_images(sub, count=2)
        self._make_fake_images(tmp_path, count=1)
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        assert len(result.items) == 3

    def test_scan_multiple_extensions(self, tmp_path: Path):
        for ext in [".jpg", ".png", ".heic", ".webp"]:
            (tmp_path / f"photo{ext}").write_bytes(b"\x00" * 50)
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        assert len(result.items) == 4

    def test_scan_item_has_expected_fields(self, tmp_path: Path):
        self._make_fake_images(tmp_path, count=1)
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        item = result.items[0]
        expected_keys = {
            "asset_local_id", "path", "filename", "extension", "file_size",
            "file_hash", "modified_at", "capture_timestamp",
            "camera_make", "camera_model", "lens_model",
            "focal_length", "aperture", "exposure_time", "iso",
            "image_width", "image_height", "orientation",
            "latitude", "longitude", "altitude", "image_type",
        }
        assert expected_keys.issubset(set(item.keys()))


# ---------------------------------------------------------------------------
# classify_image_type
# ---------------------------------------------------------------------------

class TestClassifyImageType:
    def _base_photo(self, **overrides) -> dict:
        """A realistic photo item with full EXIF."""
        base = {
            "filename": "IMG_1234.JPG",
            "extension": ".jpg",
            "camera_make": "Apple",
            "camera_model": "iPhone 15 Pro",
            "lens_model": "iPhone 15 Pro back camera 6.765mm f/1.78",
            "focal_length": "6.8mm",
            "aperture": "f/1.8",
            "iso": "100",
            "exposure_time": "1/120s",
            "image_width": 4032,
            "image_height": 3024,
            "software": "",
        }
        base.update(overrides)
        return base

    def _base_screenshot(self, **overrides) -> dict:
        """A typical iOS screenshot."""
        base = {
            "filename": "Screenshot 2024-06-15 at 14.30.00.png",
            "extension": ".png",
            "camera_make": "",
            "camera_model": "",
            "lens_model": "",
            "focal_length": "",
            "aperture": "",
            "iso": "",
            "exposure_time": "",
            "image_width": 1179,
            "image_height": 2556,
            "software": "17.5",
        }
        base.update(overrides)
        return base

    def test_real_photo_classified_as_photo(self):
        assert classify_image_type(self._base_photo()) == "photo"

    def test_screenshot_by_filename(self):
        assert classify_image_type(self._base_screenshot()) == "screenshot"

    def test_chinese_screenshot_filename(self):
        item = self._base_screenshot(filename="截屏2024-06-15 14.30.00.png")
        assert classify_image_type(item) == "screenshot"

    def test_chinese_截图_filename(self):
        item = self._base_screenshot(filename="截图_20240615.png")
        assert classify_image_type(item) == "screenshot"

    def test_macos_screenshot_filename(self):
        item = self._base_screenshot(
            filename="Screenshot 2024-06-15 at 14.30.00.png",
            image_width=2560, image_height=1600,
        )
        assert classify_image_type(item) == "screenshot"

    def test_cleanshot_filename(self):
        item = self._base_screenshot(filename="CleanShot 2024-06-15.png")
        assert classify_image_type(item) == "screenshot"

    def test_png_no_exif_apple_device(self):
        """PNG from Apple device with no camera EXIF = likely screenshot."""
        item = {
            "filename": "IMG_0042.PNG",
            "extension": ".png",
            "camera_make": "Apple",
            "camera_model": "iPhone 15 Pro",
            "lens_model": "",
            "focal_length": "",
            "aperture": "",
            "iso": "",
            "image_width": 1179,
            "image_height": 2556,
            "software": "17.5",
        }
        assert classify_image_type(item) == "screenshot"

    def test_photo_with_screen_dimensions_but_full_exif(self):
        """Full EXIF data = photo even if dimensions happen to match screen."""
        item = self._base_photo(image_width=1920, image_height=1080)
        assert classify_image_type(item) == "photo"

    def test_png_with_real_camera_exif_is_photo(self):
        """Camera-shot PNG should still be classified as photo."""
        item = self._base_photo(filename="IMG_1234.png", extension=".png")
        assert classify_image_type(item) == "photo"

    def test_no_metadata_jpg_is_photo(self):
        """JPG with no metadata at all defaults to photo (conservative)."""
        item = {
            "filename": "DSC_0001.jpg",
            "extension": ".jpg",
            "camera_make": "",
            "camera_model": "",
            "lens_model": "",
            "focal_length": "",
            "aperture": "",
            "iso": "",
            "image_width": 0,
            "image_height": 0,
            "software": "",
        }
        assert classify_image_type(item) == "photo"

    def test_ios_version_software_is_screenshot_signal(self):
        """Software tag with pure version like '17.5' is an iOS screenshot signal."""
        item = self._base_screenshot(filename="IMG_0099.PNG")
        # No screenshot keyword in filename, but has: no EXIF, iOS version software,
        # screen dimensions, PNG from Apple → enough signals
        assert classify_image_type(item) == "screenshot"
