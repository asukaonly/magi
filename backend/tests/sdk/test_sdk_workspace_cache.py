from pathlib import Path


def test_resolve_session_cache_roundtrip(tmp_path: Path):
    from magi_plugin_sdk.workspace_cache import resolve_session_cache

    sc = resolve_session_cache(str(tmp_path), "session-1")
    ref = sc.write_snapshot(b"hello")
    assert sc.read_snapshot(ref) == b"hello"
