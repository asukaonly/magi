"""Tests for photo-library reader — EXIF extraction, classification, scan, exclude patterns."""
from __future__ import annotations

import importlib.util
import os
import struct
import sys
from pathlib import Path

import pytest

# Load reader module from plugin directory
_reader_path = Path(__file__).resolve().parents[3] / "plugins" / "photo-library" / "reader.py"
_spec = importlib.util.spec_from_file_location(
    "photo_library_reader",
    _reader_path,
    submodule_search_locations=[str(_reader_path.parent)],
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

PhotoLibraryReader = _mod.PhotoLibraryReader
ScanResult = _mod.ScanResult
classify_image_type = _mod.classify_image_type
extract_exif = _mod.extract_exif
_file_hash_quick = _mod._file_hash_quick
_parse_exif_datetime = _mod._parse_exif_datetime
_matches_any_pattern = _mod._matches_any_pattern
IMAGE_EXTENSIONS = _mod.IMAGE_EXTENSIONS


# ---------------------------------------------------------------------------
# _parse_exif_datetime
# ---------------------------------------------------------------------------

class TestParseExifDatetime:
    def test_valid_datetime(self):
        ts = _parse_exif_datetime("2024:03:09 12:00:00")
        assert ts > 0
        # Verify it's roughly March 2024
        assert 1709_900_000 < ts < 1710_100_000

    def test_empty_string(self):
        assert _parse_exif_datetime("") == 0.0

    def test_short_string(self):
        assert _parse_exif_datetime("2024") == 0.0

    def test_null_terminated(self):
        ts = _parse_exif_datetime("2024:03:09 12:00:00\x00")
        assert ts > 0

    def test_invalid_format(self):
        assert _parse_exif_datetime("not-a-date-string") == 0.0


# ---------------------------------------------------------------------------
# _file_hash_quick
# ---------------------------------------------------------------------------

class TestFileHashQuick:
    def test_returns_hex_string(self, tmp_path: Path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"\xff" * 1000)
        h = _file_hash_quick(f)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_content_different_hash(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"\x00" * 100)
        b.write_bytes(b"\xff" * 100)
        assert _file_hash_quick(a) != _file_hash_quick(b)

    def test_missing_file_returns_empty(self, tmp_path: Path):
        missing = tmp_path / "no_such_file.bin"
        assert _file_hash_quick(missing) == ""


# ---------------------------------------------------------------------------
# _matches_any_pattern
# ---------------------------------------------------------------------------

class TestMatchesAnyPattern:
    def test_simple_match(self):
        assert _matches_any_pattern("thumbnails", ["thumbnails"])

    def test_glob_star(self):
        assert _matches_any_pattern("a/b/thumbnails", ["**/thumbnails"])

    def test_no_match(self):
        assert not _matches_any_pattern("photos/2024", ["thumbnails", ".cache"])

    def test_nested_glob(self):
        assert _matches_any_pattern("deep/nested/.cache", ["**/.cache"])

    def test_backslash_normalized(self):
        # Windows-style paths should be normalized
        assert _matches_any_pattern("a\\thumbnails", ["*/thumbnails"])

    def test_empty_patterns(self):
        assert not _matches_any_pattern("anything", [])

    def test_wildcard_extension(self):
        assert _matches_any_pattern("photos/thumb.db", ["*.db"])


# ---------------------------------------------------------------------------
# classify_image_type
# ---------------------------------------------------------------------------

class TestClassifyImageType:
    def test_plain_photo(self):
        item = {
            "filename": "IMG_1234.jpg",
            "extension": ".jpg",
            "lens_model": "RF 50mm",
            "focal_length": "50.0mm",
            "iso": "400",
            "camera_make": "Canon",
            "software": "",
            "image_width": 8192,
            "image_height": 5464,
        }
        assert classify_image_type(item) == "photo"

    def test_screenshot_by_filename(self):
        item = {
            "filename": "Screenshot 2024-03-09.png",
            "extension": ".png",
            "lens_model": "",
            "focal_length": "",
            "iso": "",
            "camera_make": "",
            "software": "",
            "image_width": 0,
            "image_height": 0,
        }
        assert classify_image_type(item) == "screenshot"

    def test_screenshot_chinese_filename(self):
        item = {
            "filename": "截屏2024-03-09.png",
            "extension": ".png",
            "lens_model": "",
            "focal_length": "",
            "iso": "",
            "camera_make": "",
            "software": "",
            "image_width": 0,
            "image_height": 0,
        }
        assert classify_image_type(item) == "screenshot"

    def test_screenshot_by_heuristics(self):
        """No camera EXIF + OS version software + known screen dimensions → screenshot."""
        item = {
            "filename": "photo.png",
            "extension": ".png",
            "lens_model": "",
            "focal_length": "",
            "iso": "",
            "camera_make": "Apple",
            "software": "16.0",
            "image_width": 1179,
            "image_height": 2556,
        }
        result = classify_image_type(item)
        assert result == "screenshot"

    def test_photo_with_camera_exif(self):
        """Full camera EXIF should not be classified as screenshot even with matching dims."""
        item = {
            "filename": "DSC00001.jpg",
            "extension": ".jpg",
            "lens_model": "FE 24-70mm F2.8 GM",
            "focal_length": "35.0mm",
            "iso": "200",
            "camera_make": "Sony",
            "software": "",
            "image_width": 1920,
            "image_height": 1080,  # known screen dim but has full EXIF
        }
        assert classify_image_type(item) == "photo"

    def test_photo_minimal_metadata(self):
        """Image with no camera info but no screenshot signals either."""
        item = {
            "filename": "image001.jpg",
            "extension": ".jpg",
            "lens_model": "",
            "focal_length": "",
            "iso": "",
            "camera_make": "Nikon",
            "software": "",
            "image_width": 4000,
            "image_height": 3000,
        }
        # score=1 for no lens/focal/iso; not enough for screenshot threshold
        assert classify_image_type(item) == "photo"


# ---------------------------------------------------------------------------
# extract_exif – JPEG
# ---------------------------------------------------------------------------

def _build_minimal_jpeg_with_exif(
    *,
    make: str = "TestCam",
    model: str = "X100",
) -> bytes:
    """Build a minimal JPEG file with an EXIF APP1 segment containing Make and Model."""
    byte_order = b"MM"  # big-endian
    bo = ">"

    # Build IFD0 entries: Make and Model
    entries = []
    string_data = b""
    ifd_offset = 8  # starts right after TIFF header

    # Make tag
    make_bytes = make.encode("ascii") + b"\x00"
    entries.append(struct.pack(bo + "HHI", 0x010F, 2, len(make_bytes)))
    # Model tag
    model_bytes = model.encode("ascii") + b"\x00"
    entries.append(struct.pack(bo + "HHI", 0x0110, 2, len(model_bytes)))

    num_entries = len(entries)
    ifd_size = 2 + num_entries * 12 + 4  # count + entries + next_ifd
    data_offset = ifd_offset + ifd_size

    # Rebuild entries with correct offsets for values > 4 bytes
    ifd_data = struct.pack(bo + "H", num_entries)
    current_data_offset = data_offset

    # Make entry
    if len(make_bytes) <= 4:
        val = make_bytes.ljust(4, b"\x00")
        ifd_data += struct.pack(bo + "HHI", 0x010F, 2, len(make_bytes)) + val
    else:
        ifd_data += struct.pack(bo + "HHI", 0x010F, 2, len(make_bytes))
        ifd_data += struct.pack(bo + "I", current_data_offset)
        string_data += make_bytes
        current_data_offset += len(make_bytes)

    # Model entry
    if len(model_bytes) <= 4:
        val = model_bytes.ljust(4, b"\x00")
        ifd_data += struct.pack(bo + "HHI", 0x0110, 2, len(model_bytes)) + val
    else:
        ifd_data += struct.pack(bo + "HHI", 0x0110, 2, len(model_bytes))
        ifd_data += struct.pack(bo + "I", current_data_offset)
        string_data += model_bytes
        current_data_offset += len(model_bytes)

    # Next IFD = 0
    ifd_data += struct.pack(bo + "I", 0)

    # Build TIFF header
    tiff_header = byte_order + b"\x00\x2a" + struct.pack(bo + "I", ifd_offset)
    exif_body = tiff_header + ifd_data + string_data

    # Build APP1 segment
    exif_header = b"Exif\x00\x00"
    app1_payload = exif_header + exif_body
    app1_length = len(app1_payload) + 2
    app1 = b"\xff\xe1" + struct.pack(">H", app1_length) + app1_payload

    # Build JPEG
    return b"\xff\xd8" + app1 + b"\xff\xd9"


def _build_minimal_heic_with_exif(
    *,
    make: str = "Apple",
    model: str = "iPhone 15 Pro",
) -> bytes:
    """Build a minimal HEIC-like ISOBMFF file with ftyp + meta > iprp > ipco > Exif."""
    bo = ">"  # big-endian TIFF

    # Build the embedded TIFF EXIF payload (same style as the JPEG helper)
    make_bytes = make.encode("ascii") + b"\x00"
    model_bytes = model.encode("ascii") + b"\x00"

    ifd_offset = 8
    num_entries = 2
    ifd_size = 2 + num_entries * 12 + 4
    data_offset = ifd_offset + ifd_size

    ifd_data = struct.pack(bo + "H", num_entries)
    current_data_offset = data_offset
    string_data = b""

    # Make entry
    if len(make_bytes) <= 4:
        ifd_data += struct.pack(bo + "HHI", 0x010F, 2, len(make_bytes))
        ifd_data += make_bytes.ljust(4, b"\x00")
    else:
        ifd_data += struct.pack(bo + "HHI", 0x010F, 2, len(make_bytes))
        ifd_data += struct.pack(bo + "I", current_data_offset)
        string_data += make_bytes
        current_data_offset += len(make_bytes)

    # Model entry
    if len(model_bytes) <= 4:
        ifd_data += struct.pack(bo + "HHI", 0x0110, 2, len(model_bytes))
        ifd_data += model_bytes.ljust(4, b"\x00")
    else:
        ifd_data += struct.pack(bo + "HHI", 0x0110, 2, len(model_bytes))
        ifd_data += struct.pack(bo + "I", current_data_offset)
        string_data += model_bytes
        current_data_offset += len(model_bytes)

    ifd_data += struct.pack(bo + "I", 0)  # next IFD = 0

    tiff_header = b"MM\x00\x2a" + struct.pack(bo + "I", ifd_offset)
    tiff_body = tiff_header + ifd_data + string_data

    # Exif property box: 4-byte TIFF offset prefix (0) + TIFF data
    exif_payload = struct.pack(">I", 0) + tiff_body
    exif_box = struct.pack(">I", 8 + len(exif_payload)) + b"Exif" + exif_payload

    # ipco box
    ipco_box = struct.pack(">I", 8 + len(exif_box)) + b"ipco" + exif_box

    # iprp box
    iprp_box = struct.pack(">I", 8 + len(ipco_box)) + b"iprp" + ipco_box

    # meta box (FullBox: version=0, flags=0)
    meta_payload = struct.pack(">I", 0) + iprp_box  # 4-byte version+flags
    meta_box = struct.pack(">I", 8 + len(meta_payload)) + b"meta" + meta_payload

    # ftyp box
    ftyp_payload = b"heic" + b"heic"
    ftyp_box = struct.pack(">I", 8 + len(ftyp_payload)) + b"ftyp" + ftyp_payload

    return ftyp_box + meta_box


class TestExtractExif:
    def test_jpeg_basic_tags(self, tmp_path: Path):
        jpeg_data = _build_minimal_jpeg_with_exif(make="Canon", model="EOS R5")
        f = tmp_path / "test.jpg"
        f.write_bytes(jpeg_data)
        result = extract_exif(f)
        assert result.get("camera_make") == "Canon"
        assert result.get("camera_model") == "EOS R5"

    def test_non_exif_file(self, tmp_path: Path):
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = extract_exif(f)
        assert result == {}

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.jpg"
        f.write_bytes(b"")
        result = extract_exif(f)
        assert result == {}

    def test_corrupt_jpeg(self, tmp_path: Path):
        f = tmp_path / "corrupt.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe1\x00\x04XX")
        result = extract_exif(f)
        assert isinstance(result, dict)

    def test_tiff_header(self, tmp_path: Path):
        """TIFF files with II/MM header should be attempted."""
        # Minimal big-endian TIFF with no real IFD
        tiff_data = b"MM\x00\x2a\x00\x00\x00\x08\x00\x00"
        f = tmp_path / "test.tif"
        f.write_bytes(tiff_data)
        result = extract_exif(f)
        assert isinstance(result, dict)

    def test_heic_with_exif(self, tmp_path: Path):
        """HEIC file with an Exif property box should have EXIF extracted."""
        heic_data = _build_minimal_heic_with_exif(make="Apple", model="iPhone 15 Pro")
        f = tmp_path / "test.heic"
        f.write_bytes(heic_data)
        result = extract_exif(f)
        assert result.get("camera_make") == "Apple"
        assert result.get("camera_model") == "iPhone 15 Pro"

    def test_heic_without_exif(self, tmp_path: Path):
        """HEIC file without Exif box should return empty dict."""
        # Minimal ftyp box only
        ftyp = b"heic"
        ftyp_payload = ftyp + b"heic"
        ftyp_box = struct.pack(">I", 8 + len(ftyp_payload)) + b"ftyp" + ftyp_payload
        f = tmp_path / "no_exif.heic"
        f.write_bytes(ftyp_box)
        result = extract_exif(f)
        assert result == {}


# ---------------------------------------------------------------------------
# PhotoLibraryReader.scan_directory
# ---------------------------------------------------------------------------

class TestScanDirectory:
    def test_scans_image_files(self, tmp_path: Path):
        (tmp_path / "photo1.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 100)
        (tmp_path / "photo2.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
        (tmp_path / "readme.txt").write_text("not an image")

        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        # Should find the two image files, not the txt
        assert len(result.items) == 2
        assert result.total_scanned == 2
        filenames = {it["filename"] for it in result.items}
        assert filenames == {"photo1.jpg", "photo2.png"}

    def test_limit_respected(self, tmp_path: Path):
        for i in range(5):
            (tmp_path / f"img{i}.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path), limit=2)
        assert len(result.items) == 2

    def test_min_modified_at_filter(self, tmp_path: Path):
        import time
        old = tmp_path / "old.jpg"
        old.write_bytes(b"\xff\xd8" + b"\x00" * 50)
        # Set mtime to past
        os.utime(old, (1000.0, 1000.0))

        new = tmp_path / "new.jpg"
        new.write_bytes(b"\xff\xd8" + b"\x00" * 50)

        reader = PhotoLibraryReader()
        result = reader.scan_directory(
            str(tmp_path),
            min_modified_at=time.time() - 60,
        )
        # Only the recently created file should pass
        assert len(result.items) == 1
        assert result.items[0]["filename"] == "new.jpg"

    def test_nonexistent_directory(self, tmp_path: Path):
        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path / "no_such_dir"))
        assert result.items == []
        assert result.total_scanned == 0

    def test_exclude_patterns_prune_directories(self, tmp_path: Path):
        # Create directory structure:
        #  photos/
        #    good.jpg
        #    thumbnails/
        #      thumb.jpg
        #    .cache/
        #      cached.jpg
        (tmp_path / "good.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        thumbs = tmp_path / "thumbnails"
        thumbs.mkdir()
        (thumbs / "thumb.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        cache = tmp_path / ".cache"
        cache.mkdir()
        (cache / "cached.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        reader = PhotoLibraryReader()
        result = reader.scan_directory(
            str(tmp_path),
            exclude_patterns=["thumbnails", ".cache"],
        )
        assert len(result.items) == 1
        assert result.items[0]["filename"] == "good.jpg"

    def test_exclude_patterns_glob(self, tmp_path: Path):
        """Glob patterns like **/.hidden should work."""
        visible = tmp_path / "visible"
        visible.mkdir()
        (visible / "a.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "b.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        reader = PhotoLibraryReader()
        result = reader.scan_directory(
            str(tmp_path),
            exclude_patterns=[".*"],  # exclude dot-directories
        )
        filenames = {it["filename"] for it in result.items}
        assert "a.jpg" in filenames
        assert "b.jpg" not in filenames

    def test_nested_directory_scan(self, tmp_path: Path):
        sub = tmp_path / "2024" / "march"
        sub.mkdir(parents=True)
        (sub / "vacation.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)
        (tmp_path / "root.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        assert len(result.items) == 2

    def test_item_fields_populated(self, tmp_path: Path):
        (tmp_path / "test.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 100)

        reader = PhotoLibraryReader()
        result = reader.scan_directory(str(tmp_path))
        assert len(result.items) == 1
        item = result.items[0]
        # Verify required fields are populated
        assert item["filename"] == "test.jpg"
        assert item["extension"] == ".jpg"
        assert item["file_size"] > 0
        assert item["file_hash"] != ""
        assert item["modified_at"] > 0
        assert item["path"].endswith("test.jpg")
        assert "asset_local_id" in item
        assert "image_type" in item
