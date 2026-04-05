from __future__ import annotations

from pathlib import Path


def test_tauri_debug_prefers_python_backend_pair() -> None:
    """Verify debug desktop startup spawns the IPC worker Python backend."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    assert "let start = if cfg!(debug_assertions)" in source
    assert "spawn_dev_backend_pair(&session_token, &ipc_socket_path)" in source


def test_tauri_dev_backend_does_not_discard_logs() -> None:
    """Verify dev backend fallback keeps stdout/stderr visible for debugging."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    spawn_dev_section = source.split("fn spawn_dev_backend_role", 1)[1].split("fn spawn_sidecar_backend", 1)[0]
    assert ".stdout(Stdio::null())" not in spawn_dev_section
    assert ".stderr(Stdio::null())" not in spawn_dev_section


def test_tauri_spawns_unified_role() -> None:
    """Verify desktop runtime spawns the IPC worker Python process."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    assert '"ipc_worker"' in source
    # IPC worker mode spawns a single process tracked as python_process
    assert "python_process:" in source
    # No separate runtime_worker_process field
    assert "runtime_worker_process:" not in source


def test_axum_native_routes_cover_read_endpoints() -> None:
    """Verify Axum router registers native Rust routes for all read-only endpoints."""
    mod_path = (
        Path(__file__).resolve().parents[3]
        / "crates"
        / "magi-gateway"
        / "src"
        / "api"
        / "mod.rs"
    )
    source = mod_path.read_text(encoding="utf-8")

    expected_routes = [
        "/api/health",
        "/api/ready",
        "/api/messages/sessions",
        "/api/messages/history",
        "/api/messages/trace",
        "/api/tasks",
        "/api/tasks/{task_id}",
        "/api/tasks/orchestration/{orchestration_id}",
        "/api/schedules",
        "/api/schedules/executions/recent",
        "/api/schedules/{schedule_id}",
        "/api/schedules/{schedule_id}/executions",
        "/api/metrics/llm/usage/summary",
        "/api/metrics/llm/usage/timeseries",
        "/api/memory/l1/events",
        "/api/memory/l2/relations",
        "/api/memory/l2/assertions",
        "/api/memory/l2/entities",
        "/api/memory/l2/mentions",
        "/api/memory/l2/snapshots",
        "/api/memory/l2/conflict-rules",
        "/api/memory/l3/summaries",
        "/api/personality",
        "/api/personality/current",
        "/api/personality/greeting",
        "/api/personality/compare/{from_name}/{to_name}",
        "/api/personality/{name}",
        "/api/personalities",
        "/api/personalities/{preset_id}",
        "/api/llm/providers/custom-template",
        "/api/local-embedding/discovered",
    ]
    for route in expected_routes:
        assert route in source, f"Missing native Rust route: {route}"
