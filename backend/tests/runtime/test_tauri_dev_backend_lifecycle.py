from __future__ import annotations

import json
from pathlib import Path


def test_service_worker_environment_excludes_client_credentials() -> None:
    """Keep client authorization at the Rust boundary, outside Python."""
    root = Path(__file__).resolve().parents[3]
    source = (root / "crates/magi-server-runtime/src/supervisor.rs").read_text(encoding="utf-8")
    worker_spawn = source.split("impl WorkerProcess", 1)[1].split("async fn stop", 1)[0]
    assert '.env_remove("MAGI_DESKTOP_SESSION_TOKEN")' in worker_spawn
    assert '.env_remove("MAGI_EXTERNAL_BACKEND_SESSION_TOKEN")' in worker_spawn
    assert '.env("MAGI_IPC_AUTH_TOKEN", token)' in worker_spawn
    assert 'session_token' not in worker_spawn


def test_tauri_protects_private_data_before_opening_logs() -> None:
    """Verify access protection is installed before any desktop log file is opened."""
    source_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "src" / "main.rs"
    source = source_path.read_text(encoding="utf-8")
    main_section = source.split("fn main()", 1)[1]

    protection_index = main_section.index("private_data::protect_magi_data_root")
    logging_index = main_section.index("DesktopLogRuntime::install")
    assert protection_index < logging_index


def test_tauri_webview_has_a_restrictive_content_policy() -> None:
    """Allow configured HTTPS centers while excluding insecure remote origins."""
    config_path = Path(__file__).resolve().parents[3] / "frontend" / "src-tauri" / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    policy = config["app"]["security"]["csp"]

    assert isinstance(policy, dict)
    assert policy["object-src"] == ["'none'"]
    assert policy["frame-src"] == ["'none'"]
    assert "https:" in policy["connect-src"]
    assert "http:" not in policy["connect-src"]
    assert "http://127.0.0.1:*" in policy["connect-src"]


def test_axum_declares_expected_native_read_endpoints() -> None:
    """Verify Axum registers only the read endpoints owned by the gateway."""
    mod_path = (
        Path(__file__).resolve().parents[3] / "crates" / "magi-gateway" / "src" / "api" / "mod.rs"
    )
    source = mod_path.read_text(encoding="utf-8")

    expected_routes = [
        "/api/health",
        "/api/ready",
        "/api/messages/sessions",
        "/api/schedules",
        "/api/schedules/executions/recent",
        "/api/schedules/{schedule_id}",
        "/api/schedules/{schedule_id}/executions",
        "/api/metrics/llm/usage/summary",
        "/api/metrics/llm/usage/timeseries",
        "/api/memory/l1/events",
        "/api/memory/l2/entities",
        "/api/memory/l2/mentions",
        "/api/memory/l2/conflict-rules",
        "/api/memory/l3/summaries",
        "/api/llm/providers/custom-template",
        "/api/local-embedding/discovered",
    ]
    for route in expected_routes:
        assert route in source, f"Missing native Rust route: {route}"
    assert '"/api/tasks"' not in source
    assert '"/api/tasks/{task_id}"' not in source
