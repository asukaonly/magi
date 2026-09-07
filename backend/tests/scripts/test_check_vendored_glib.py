from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "check_vendored_glib", ROOT / "scripts/check-vendored-glib.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def patched_tree(tmp_path: Path) -> Path:
    shutil.copytree(
        ROOT / "vendor",
        tmp_path / "vendor",
        ignore=shutil.ignore_patterns("target", "Cargo.lock"),
    )
    shutil.copyfile(ROOT / "Cargo.toml", tmp_path / "Cargo.toml")
    return tmp_path


def test_reviewed_glib_patch_matches_upstream_files() -> None:
    assert MODULE.validate_patch() == []


def test_reverting_the_safety_fix_is_rejected(patched_tree: Path) -> None:
    source = patched_tree / "vendor/glib/src/variant_iter.rs"
    source.write_text(source.read_text().replace("&mut p,", "&p,"))
    assert MODULE.validate_patch(patched_tree) == [
        "GLib source checksum mismatch: src/variant_iter.rs"
    ]


def test_disconnected_override_is_rejected(patched_tree: Path) -> None:
    manifest = patched_tree / "Cargo.toml"
    manifest.write_text(
        manifest.read_text().replace('path = "vendor/glib"', 'version = "0.18"')
    )
    assert (
        "The workspace must use the reviewed local GLib patch"
        in MODULE.validate_patch(patched_tree)
    )


def test_missing_and_unreviewed_sources_are_rejected(patched_tree: Path) -> None:
    (patched_tree / "vendor/glib/src/lib.rs").unlink()
    (patched_tree / "vendor/glib/src/unreviewed.rs").write_text(
        "// Unreviewed change\n"
    )
    failures = MODULE.validate_patch(patched_tree)
    assert "Missing GLib source: src/lib.rs" in failures
    assert "Unexpected GLib source: src/unreviewed.rs" in failures
