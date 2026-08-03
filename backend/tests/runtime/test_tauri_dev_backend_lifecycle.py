from __future__ import annotations

import json
from pathlib import Path


def test_tauri_debug_prefers_python_backend_pair() -> None:
    """Verify debug desktop startup spawns the IPC worker Python backend."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    assert "let start = if cfg!(debug_assertions)" in source
    debug_start = source.split("let start = if cfg!(debug_assertions)", 1)[1].split("} else {", 1)[
        0
    ]
    assert "spawn_dev_backend_pair(" in debug_start
    assert "&ipc_socket_path" in debug_start
    assert "pending_full_data_clear" in debug_start


def test_tauri_does_not_expose_session_token_to_python_backend() -> None:
    """Verify Python worker commands never receive the gateway session credential."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    sidecar_section = source.split("fn spawn_sidecar_role", 1)[1].split("fn find_project_root", 1)[
        0
    ]
    dev_section = source.split("fn spawn_dev_backend_role", 1)[1].split(
        "fn spawn_sidecar_backend", 1
    )[0]
    isolation_section = source.split("fn isolate_python_worker_environment", 1)[1].split(
        "#[cfg(unix)]", 1
    )[0]

    for python_spawn_section in (sidecar_section, dev_section):
        assert "isolate_python_worker_environment(&mut command)" in python_spawn_section
        assert (
            "configure_ipc_auth_environment(&mut command, ipc_auth_token)" in python_spawn_section
        )
        assert "MAGI_DESKTOP_SESSION_TOKEN" not in python_spawn_section
        assert "session_token: &str" not in python_spawn_section
    assert "command.env_remove(DESKTOP_SESSION_TOKEN_ENV)" in isolation_section
    assert "command.env_remove(INTERNAL_IPC_TOKEN_ENV)" in isolation_section


def test_tauri_webview_has_a_restrictive_content_policy() -> None:
    """Verify packaged pages cannot execute or connect to arbitrary origins."""
    config_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    policy = config["app"]["security"]["csp"]

    assert isinstance(policy, dict)
    assert policy["object-src"] == ["'none'"]
    assert policy["frame-src"] == ["'none'"]
    assert "https:" not in policy["connect-src"]
    assert "http:" not in policy["connect-src"]
    assert "http://127.0.0.1:*" in policy["connect-src"]


def test_tauri_dev_backend_does_not_discard_logs() -> None:
    """Verify dev backend fallback keeps stdout/stderr visible for debugging."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")

    spawn_dev_section = source.split("fn spawn_dev_backend_role", 1)[1].split(
        "fn spawn_sidecar_backend", 1
    )[0]
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
        Path(__file__).resolve().parents[3] / "crates" / "magi-gateway" / "src" / "api" / "mod.rs"
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
        "/api/llm/providers/custom-template",
        "/api/local-embedding/discovered",
    ]
    for route in expected_routes:
        assert route in source, f"Missing native Rust route: {route}"
