use std::path::{Path, PathBuf};
#[cfg(test)]
use std::sync::{Mutex, MutexGuard};
use std::sync::{OnceLock, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{Connection, OpenFlags};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/// Resolve the Magi base directory (~/.magi).
pub fn magi_base_dir() -> PathBuf {
    if let Some(path) = magi_base_dir_override()
        .read()
        .ok()
        .and_then(|guard| guard.clone())
    {
        return path;
    }

    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".magi")
}

static MAGI_BASE_DIR_OVERRIDE: OnceLock<RwLock<Option<PathBuf>>> = OnceLock::new();

fn magi_base_dir_override() -> &'static RwLock<Option<PathBuf>> {
    MAGI_BASE_DIR_OVERRIDE.get_or_init(|| RwLock::new(None))
}

#[doc(hidden)]
pub fn set_magi_base_dir_override_for_tests(path: Option<PathBuf>) -> Option<PathBuf> {
    let mut guard = magi_base_dir_override()
        .write()
        .expect("lock Magi base dir override");
    std::mem::replace(&mut *guard, path)
}

#[cfg(test)]
static MAGI_BASE_DIR_OVERRIDE_TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

#[cfg(test)]
pub fn magi_base_dir_override_test_lock() -> MutexGuard<'static, ()> {
    MAGI_BASE_DIR_OVERRIDE_TEST_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .expect("lock Magi base dir override test mutex")
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
    open_readonly_result(path).ok()
}

/// Open a database in read-only mode while preserving the SQLite error.
pub fn open_readonly_result(path: &std::path::Path) -> rusqlite::Result<Connection> {
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
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
    query_to_json_array_result(conn, sql, params).unwrap_or_default()
}

/// Execute a SQL query without collapsing database errors into an empty result.
pub fn query_to_json_array_result(
    conn: &Connection,
    sql: &str,
    params: &[&dyn rusqlite::types::ToSql],
) -> rusqlite::Result<Vec<Value>> {
    let mut stmt = conn.prepare(sql)?;
    let col_names: Vec<String> = stmt.column_names().iter().map(|s| s.to_string()).collect();
    let rows = stmt.query_map(params, |row| {
        let mut obj = serde_json::Map::new();
        for (i, name) in col_names.iter().enumerate() {
            let val = value_ref_to_json(row.get_ref(i)?);
            obj.insert(name.clone(), val);
        }
        Ok(Value::Object(obj))
    })?;
    rows.collect()
}

/// Execute a `SELECT COUNT(*)` query and return the result.
pub fn count_rows(conn: &Connection, sql: &str, params: &[&dyn rusqlite::types::ToSql]) -> i64 {
    count_rows_result(conn, sql, params).unwrap_or(0)
}

/// Count rows without collapsing database errors into zero.
pub fn count_rows_result(
    conn: &Connection,
    sql: &str,
    params: &[&dyn rusqlite::types::ToSql],
) -> rusqlite::Result<i64> {
    conn.query_row(sql, params, |row| row.get::<_, i64>(0))
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or(0)
}

/// Insert a row into `runtime_notifications` so the notification bridge
/// picks it up and emits it to the frontend via Tauri events.
pub fn emit_notification(channel: &str, user_id: &str, session_id: &str, payload: &Value) {
    let path = runtime_trace_db_path();
    let conn = match open_readwrite(&path) {
        Some(c) => c,
        None => return,
    };
    let payload_json = serde_json::to_string(payload).unwrap_or_default();
    conn.execute(
        "INSERT INTO runtime_notifications (channel, user_id, session_id, payload_json, created_at_ms) \
         VALUES (?1, ?2, ?3, ?4, ?5)",
        rusqlite::params![channel, user_id, session_id, payload_json, now_ms()],
    )
    .ok();
}

/// Ensure performance-critical indexes exist on memory databases.
/// Called once at startup; uses `CREATE INDEX IF NOT EXISTS` so it is idempotent.
pub fn ensure_indexes() {
    // memory.db indexes
    if let Some(conn) = open_readwrite(&memory_db_path()) {
        let stmts = [
            "CREATE INDEX IF NOT EXISTS idx_kg_status_updated \
             ON knowledge_graph(status, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_tom_assertions_updated \
             ON tom_trait_assertions(updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_summaries_updated \
             ON summaries(updated_at DESC)",
        ];
        for sql in &stmts {
            if let Err(e) = conn.execute_batch(sql) {
                eprintln!("ensure_indexes: {e}");
            }
        }
    }

    // l1_events.db indexes
    if let Some(conn) = open_readwrite(&l1_events_db_path()) {
        let stmts = ["CREATE INDEX IF NOT EXISTS idx_fact_events_deleted_at \
             ON fact_events(deleted_at) WHERE deleted_at IS NOT NULL"];
        for sql in &stmts {
            if let Err(e) = conn.execute_batch(sql) {
                eprintln!("ensure_indexes: {e}");
            }
        }
    }
}
