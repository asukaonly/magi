use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};

use crate::db;

pub(super) const SCHEDULE_COLUMNS: &str = "schedule_id, target_type, target_key, trigger_type, \
    trigger_config, target_payload, metadata, enabled, job_id";

pub(super) fn open_scheduler_db() -> Option<Connection> {
    let path = db::scheduler_db_path();
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()
}

pub(super) fn serialize_schedule(row: &rusqlite::Row) -> rusqlite::Result<Value> {
    let trigger_config: String = row
        .get::<_, Option<String>>(4)?
        .unwrap_or_else(|| "{}".into());
    let target_payload: String = row
        .get::<_, Option<String>>(5)?
        .unwrap_or_else(|| "{}".into());
    let metadata: String = row
        .get::<_, Option<String>>(6)?
        .unwrap_or_else(|| "{}".into());
    let target_type = row.get::<_, String>(1)?;
    let owner_kind = if target_type == "source_sync" {
        "source_settings"
    } else if target_type == "user_agent_task" {
        "agent_created"
    } else {
        "system"
    };
    Ok(json!({
        "schedule_id": row.get::<_, String>(0)?,
        "target_type": target_type,
        "target_key": row.get::<_, String>(2)?,
        "trigger": {
            "trigger_type": row.get::<_, String>(3)?,
            "config": serde_json::from_str::<Value>(&trigger_config).unwrap_or(json!({})),
        },
        "target_payload": serde_json::from_str::<Value>(&target_payload).unwrap_or(json!({})),
        "enabled": row.get::<_, i64>(7)? != 0,
        "metadata": serde_json::from_str::<Value>(&metadata).unwrap_or(json!({})),
        "job_id": row.get::<_, Option<String>>(8)?,
        "editable": target_type != "source_sync",
        "owner_kind": owner_kind,
    }))
}
