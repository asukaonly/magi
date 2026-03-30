from __future__ import annotations

from pathlib import Path


def test_dev_tauri_hot_lets_tauri_own_backend_lifecycle() -> None:
    """Verify the dev launcher no longer runs the backend as an external service."""
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dev-tauri-hot.sh"
    script = script_path.read_text(encoding="utf-8")

    assert "MAGI_TAURI_EXTERNAL_BACKEND=1" not in script
    assert "wait_for_backend_ready" not in script
    assert "wait_for_runtime_worker_ready" not in script
    assert 'python run_server.py --role runtime_worker --no-reload\n) >' not in script
    assert 'python run_server.py --role api --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --no-reload\n) >>' not in script
    assert "npm run tauri:dev" in script
    assert "trap cleanup_on_exit EXIT INT TERM HUP QUIT" in script
    assert "cleanup_on_exit()" in script
    assert "exec env" not in script
