use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/// Resolve the Magi base directory (~/.magi).
pub fn magi_base_dir() -> PathBuf {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".magi")
}

/// Path to the backend configs directory.
pub fn backend_configs_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("backend")
        .join("configs")
}

pub fn embedding_models_dir() -> PathBuf {
    magi_base_dir().join("cache").join("models").join("embed")
}

pub fn chat_db_path() -> PathBuf {
    magi_base_dir().join("data").join("chat").join("chat.db")
}

/// Path to the runtime trace database.
pub fn runtime_trace_db_path() -> PathBuf {
    magi_base_dir().join("runtime").join("runtime_trace.db")
}

/// Path to the tasks database.
pub fn tasks_db_path() -> PathBuf {
    magi_base_dir().join("runtime").join("tasks.db")
}

/// Path to the scheduler database.
pub fn scheduler_db_path() -> PathBuf {
    magi_base_dir().join("runtime").join("scheduler.db")
}

/// Path to the LLM usage database.
pub fn llm_usage_db_path() -> PathBuf {
    magi_base_dir().join("runtime").join("llm_usage.db")
}

/// Path to the L1 events database.
pub fn l1_events_db_path() -> PathBuf {
    magi_base_dir()
        .join("data")
        .join("memory")
        .join("l1_events.db")
}

/// Path to the L2/L3 memory database.
pub fn memory_db_path() -> PathBuf {
    magi_base_dir()
        .join("data")
        .join("memory")
        .join("memory.db")
}

// ---------------------------------------------------------------------------
// SQLite query helpers
// ---------------------------------------------------------------------------

/// Open a database in read-only mode. Returns None if the file does not exist.
pub fn open_readonly(path: &std::path::Path) -> Option<Connection> {
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()
}

/// Open a database in read-write mode. Returns None if the file does not exist.
pub fn open_readwrite(path: &std::path::Path) -> Option<Connection> {
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok()
}

/// Convert a rusqlite ValueRef to a serde_json Value.
/// TEXT columns that contain valid JSON (arrays, objects) are parsed inline.
pub fn value_ref_to_json(val: rusqlite::types::ValueRef) -> Value {
    match val {
        rusqlite::types::ValueRef::Null => Value::Null,
        rusqlite::types::ValueRef::Integer(i) => serde_json::json!(i),
        rusqlite::types::ValueRef::Real(f) => serde_json::json!(f),
        rusqlite::types::ValueRef::Text(s) => {
            let s = std::str::from_utf8(s).unwrap_or("");
            serde_json::from_str(s).unwrap_or_else(|_| Value::String(s.to_string()))
        }
        rusqlite::types::ValueRef::Blob(_) => Value::Null,
    }
}

/// Execute a SQL query and return results as a JSON array of objects.
/// Column names become the JSON keys; values are auto-converted via
/// `value_ref_to_json` (TEXT columns containing JSON are parsed inline).
pub fn query_to_json_array(
    conn: &Connection,
    sql: &str,
    params: &[&dyn rusqlite::types::ToSql],
) -> Vec<Value> {
    let mut stmt = match conn.prepare(sql) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    let col_names: Vec<String> = stmt.column_names().iter().map(|s| s.to_string()).collect();
    stmt.query_map(params, |row| {
        let mut obj = serde_json::Map::new();
        for (i, name) in col_names.iter().enumerate() {
            let val = match row.get_ref(i) {
                Ok(v) => value_ref_to_json(v),
                Err(_) => Value::Null,
            };
            obj.insert(name.clone(), val);
        }
        Ok(Value::Object(obj))
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}
