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

    configured_magi_base_dir().expect("Invalid Magi data directory")
}

/// Resolve the process-wide directory shared with the desktop host and Python.
pub fn configured_magi_base_dir() -> Result<PathBuf, String> {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .map_err(|_| "Neither HOME nor USERPROFILE is set".to_string())?;
    resolve_magi_base_dir(std::env::var("MAGI_HOME").ok().as_deref(), &home)
}

fn resolve_magi_base_dir(override_path: Option<&str>, home: &Path) -> Result<PathBuf, String> {
    let Some(value) = override_path else {
        return Ok(home.join(".magi"));
    };
    let path = PathBuf::from(value);
    if value.is_empty()
        || !path.is_absolute()
        || path.parent().is_none()
        || path == home
        || path
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err("MAGI_HOME must name a dedicated absolute data directory".to_string());
    }
    Ok(path)
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

pub struct GuardedConnection {
    connection: Connection,
    _permit: tokio::sync::OwnedSemaphorePermit,
}

impl std::ops::Deref for GuardedConnection {
    type Target = Connection;
    fn deref(&self) -> &Self::Target {
        &self.connection
    }
}

impl std::ops::DerefMut for GuardedConnection {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.connection
    }
}

/// The database handle owns its maintenance permit, including inside blocking tasks.
pub fn open_readonly(path: &std::path::Path) -> Option<GuardedConnection> {
    open_readonly_result(path).ok()
}

pub fn open_readonly_result(path: &std::path::Path) -> rusqlite::Result<GuardedConnection> {
    let permit = crate::database_gate::global().enter().ok_or_else(|| {
        rusqlite::Error::SqliteFailure(
            rusqlite::ffi::Error::new(rusqlite::ffi::SQLITE_BUSY),
            Some("Center maintenance is active".into()),
        )
    })?;
    let connection = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    Ok(GuardedConnection {
        connection,
        _permit: permit,
    })
}

pub fn open_readwrite(path: &std::path::Path) -> Option<GuardedConnection> {
    let permit = crate::database_gate::global().enter()?;
    if !path.exists() {
        return None;
    }
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok()?;
    Some(GuardedConnection {
        connection,
        _permit: permit,
    })
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

#[cfg(test)]
mod data_root_tests {
    use super::resolve_magi_base_dir;
    use std::path::Path;

    #[test]
    fn selects_dedicated_data_root_without_changing_home() {
        let home = std::env::temp_dir().join("magi-test-user");
        let candidate = home.join("candidate");
        assert_eq!(
            resolve_magi_base_dir(None, &home).unwrap(),
            home.join(".magi")
        );
        assert_eq!(
            resolve_magi_base_dir(candidate.to_str(), &home).unwrap(),
            candidate
        );
        for invalid in ["", "relative", home.to_str().unwrap()] {
            assert!(resolve_magi_base_dir(Some(invalid), &home).is_err());
        }
        let root = home.ancestors().last().unwrap();
        assert!(resolve_magi_base_dir(root.to_str(), &home).is_err());
        assert!(resolve_magi_base_dir(Some("/tmp/../"), Path::new("/users/test")).is_err());
    }
}
