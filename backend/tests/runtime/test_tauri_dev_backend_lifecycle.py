from __future__ import annotations

import json
from pathlib import Path


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
