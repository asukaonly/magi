from __future__ import annotations

from pathlib import Path


def test_tauri_debug_prefers_python_backend_pair() -> None:
    """Verify debug desktop startup prefers the Python fallback backend pair."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    assert "let start = if cfg!(debug_assertions)" in source
    assert "spawn_dev_backend_pair(port, &session_token)" in source


def test_tauri_dev_backend_does_not_discard_logs() -> None:
    """Verify dev backend fallback keeps stdout/stderr visible for debugging."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    spawn_dev_section = source.split("fn spawn_dev_backend_role", 1)[1].split("fn spawn_sidecar_backend", 1)[0]
    assert ".stdout(Stdio::null())" not in spawn_dev_section
    assert ".stderr(Stdio::null())" not in spawn_dev_section
