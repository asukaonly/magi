"""Collector commands distinguish terminal guidance from automation output."""
import json
import sqlite3

import pytest

from magi.collector.cli import main


@pytest.mark.parametrize("flags", [["--json", "status"], ["status", "--json"], ["status"]])
def test_missing_queue_is_read_only_json(tmp_path, monkeypatch, capsys, flags):
    root = tmp_path / "absent"
    monkeypatch.setenv("MAGI_HOME", str(root))
    assert main(flags) == 0
    result = capsys.readouterr()
    assert json.loads(result.out)["state"] == "not_initialized"
    assert result.err == ""
    assert not root.exists()


def test_terminal_queue_report_explains_failures_and_keeps_counts_distinct(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAGI_HOME", str(tmp_path))
    monkeypatch.setenv("MAGI_CLI_LAUNCHER", "./scripts/dev-server.sh")
    with sqlite3.connect(tmp_path / "outbox.db") as db:
        db.execute("CREATE TABLE events(sequence INTEGER, attempts INTEGER, retry_at REAL, failure TEXT, terminal INTEGER)")
        db.execute("INSERT INTO events VALUES(1,3,0,'unauthorized',1)")
        db.execute("INSERT INTO events VALUES(2,0,0,NULL,0)")
    assert main(["status", "--text"]) == 0
    result = capsys.readouterr()
    assert "Waiting to send: 1" in result.out
    assert "Failed (manual action needed): 1" in result.out
    assert "unauthorized" in result.out
    assert "./scripts/dev-server.sh" in result.out
    assert "collect retry" in result.out
    assert result.err == ""


def test_collector_errors_are_on_stderr_with_no_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAGI_HOME", str(tmp_path))
    (tmp_path / "outbox.db").write_text("not a database")
    assert main(["status", "--json"]) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert json.loads(result.err)["success"] is False
    assert main(["status", "--text"]) == 1
    result = capsys.readouterr()
    assert "Inspect this collector" in result.err
    assert "Traceback" not in result.err
