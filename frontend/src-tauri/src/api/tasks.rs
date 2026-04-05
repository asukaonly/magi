use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::db;

#[derive(Deserialize)]
pub struct ListTasksQuery {
    pub user_id: String,
    pub status: Option<String>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

/// Native GET /api/tasks handler — reads tasks.db directly.
pub async fn list_tasks(Query(params): Query<ListTasksQuery>) -> Json<Value> {
    let user_id = params.user_id;
    let status = params.status;
    let limit = params.limit.unwrap_or(50).clamp(1, 200);
    let offset = params.offset.unwrap_or(0).max(0);

    let result =
        tokio::task::spawn_blocking(move || query_tasks(&user_id, status.as_deref(), limit, offset))
            .await
            .unwrap_or_else(|_| json!({"tasks": []}));
    Json(result)
}

/// Native GET /api/tasks/:task_id handler.
pub async fn get_task(Path(task_id): Path<String>) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || query_single_task(&task_id))
        .await
        .unwrap_or(None);
    match result {
        Some(task) => (StatusCode::OK, Json(json!({"task": task}))),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Task not found"})),
        ),
    }
}

/// Native GET /api/tasks/orchestration/:orchestration_id handler.
pub async fn list_tasks_by_orchestration(
    Path(orchestration_id): Path<String>,
) -> Json<Value> {
    let result =
        tokio::task::spawn_blocking(move || query_tasks_by_orchestration(&orchestration_id))
            .await
            .unwrap_or_else(|_| json!({"tasks": []}));
    Json(result)
}

fn open_tasks_db() -> Option<Connection> {
    let path = db::tasks_db_path();
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()
}

fn row_to_task(row: &rusqlite::Row) -> rusqlite::Result<Value> {
    let tags_json: String = row.get::<_, Option<String>>(5)?.unwrap_or_else(|| "[]".into());
    let tags: Value = serde_json::from_str(&tags_json).unwrap_or(json!([]));
    Ok(json!({
        "task_id": row.get::<_, String>(0)?,
        "title": row.get::<_, String>(1)?,
        "description": row.get::<_, String>(2)?,
        "status": row.get::<_, String>(3)?,
        "priority": row.get::<_, String>(4)?,
        "tags": tags,
        "due_date": row.get::<_, Option<f64>>(6)?,
        "created_by": row.get::<_, String>(7)?,
        "user_id": row.get::<_, String>(8)?,
        "session_id": row.get::<_, Option<String>>(9)?,
        "linked_orchestration_id": row.get::<_, Option<String>>(10)?,
        "linked_turn_id": row.get::<_, Option<String>>(11)?,
        "created_at": row.get::<_, f64>(12)?,
        "updated_at": row.get::<_, f64>(13)?,
    }))
}

const TASK_COLUMNS: &str = "task_id, title, description, status, priority, tags_json, \
    due_date, created_by, user_id, session_id, linked_orchestration_id, \
    linked_turn_id, created_at, updated_at";

fn query_tasks(user_id: &str, status: Option<&str>, limit: i64, offset: i64) -> Value {
    let conn = match open_tasks_db() {
        Some(c) => c,
        None => return json!({"tasks": []}),
    };
    let (query, params): (String, Vec<Box<dyn rusqlite::types::ToSql>>) = if let Some(st) = status {
        (
            format!(
                "SELECT {} FROM tasks WHERE user_id = ?1 AND status = ?2 ORDER BY updated_at DESC LIMIT ?3 OFFSET ?4",
                TASK_COLUMNS
            ),
            vec![
                Box::new(user_id.to_string()),
                Box::new(st.to_string()),
                Box::new(limit),
                Box::new(offset),
            ],
        )
    } else {
        (
            format!(
                "SELECT {} FROM tasks WHERE user_id = ?1 ORDER BY updated_at DESC LIMIT ?2 OFFSET ?3",
                TASK_COLUMNS
            ),
            vec![
                Box::new(user_id.to_string()),
                Box::new(limit),
                Box::new(offset),
            ],
        )
    };
    let mut stmt = match conn.prepare(&query) {
        Ok(s) => s,
        Err(_) => return json!({"tasks": []}),
    };
    let param_refs: Vec<&dyn rusqlite::types::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let tasks: Vec<Value> = stmt
        .query_map(param_refs.as_slice(), row_to_task)
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    json!({"tasks": tasks})
}

fn query_single_task(task_id: &str) -> Option<Value> {
    let conn = open_tasks_db()?;
    let mut stmt = conn
        .prepare(&format!(
            "SELECT {} FROM tasks WHERE task_id = ?1",
            TASK_COLUMNS
        ))
        .ok()?;
    stmt.query_row(rusqlite::params![task_id], row_to_task).ok()
}

fn query_tasks_by_orchestration(orchestration_id: &str) -> Value {
    let conn = match open_tasks_db() {
        Some(c) => c,
        None => return json!({"tasks": []}),
    };
    let mut stmt = match conn.prepare(&format!(
        "SELECT {} FROM tasks WHERE linked_orchestration_id = ?1 ORDER BY created_at ASC",
        TASK_COLUMNS
    )) {
        Ok(s) => s,
        Err(_) => return json!({"tasks": []}),
    };
    let tasks: Vec<Value> = stmt
        .query_map(rusqlite::params![orchestration_id], row_to_task)
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    json!({"tasks": tasks})
}
