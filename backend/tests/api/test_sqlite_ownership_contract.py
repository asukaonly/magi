from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_sqlite_ownership_checker(root: Path) -> ModuleType:
    checker_path = root / "scripts" / "check-sqlite-ownership.py"
    spec = importlib.util.spec_from_file_location("sqlite_ownership_checker", checker_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sqlite_ownership_contract_matches_gateway_writes() -> None:
    root = Path(__file__).resolve().parents[3]
    checker = _load_sqlite_ownership_checker(root)

    errors, inventory = checker.validate_ownership(
        root,
        root / "contracts" / "sqlite" / "gateway_writes.json",
    )

    assert errors == []
    discovered = {
        (item["file"], item["operation"], item["table"], item["index"])
        for item in inventory["discovered"]
    }
    assert (
        "crates/magi-gateway/src/api/messages/mutations.rs",
        "update",
        "chat_sessions",
        None,
    ) in discovered
    assert (
        "crates/magi-gateway/src/db.rs",
        "create_index",
        "fact_events",
        "idx_fact_events_deleted_at",
    ) in discovered


def test_sqlite_ownership_source_filter_keeps_cfg_test_items_before_production_sql() -> None:
    root = Path(__file__).resolve().parents[3]
    checker = _load_sqlite_ownership_checker(root)

    source = """
use rusqlite::Connection;
#[cfg(test)]
use std::sync::Mutex;

pub fn emit_notification(conn: &Connection) {
    conn.execute("INSERT INTO runtime_notifications (channel) VALUES (?1)", []);
}

#[cfg(test)]
mod tests {
    #[test]
    fn ignores_test_sql() {
        let sql = "INSERT INTO test_only_table (id) VALUES (1)";
    }
}
"""

    production = checker.production_source(source)

    assert "INSERT INTO runtime_notifications" in production
    assert "INSERT INTO test_only_table" not in production
