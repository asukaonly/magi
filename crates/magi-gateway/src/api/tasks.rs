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

    let result = tokio::task::spawn_blocking(move || {
        query_tasks(&user_id, status.as_deref(), limit, offset)
    })
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
pub async fn list_tasks_by_orchestration(Path(orchestration_id): Path<String>) -> Json<Value> {
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

fn open_tasks_db_rw() -> Option<Connection> {
    db::open_readwrite(&db::tasks_db_path())
}

fn row_to_task(row: &rusqlite::Row) -> rusqlite::Result<Value> {
    let tags_json: String = row
        .get::<_, Option<String>>(5)?
        .unwrap_or_else(|| "[]".into());
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

// ---------------------------------------------------------------------------
// Mutation handlers
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct CreateTaskQuery {
    pub user_id: String,
}

#[derive(Deserialize)]
pub struct TaskCreateBody {
    pub title: String,
    pub description: Option<String>,
    pub priority: Option<String>,
    pub tags: Option<Vec<String>>,
    pub due_date: Option<f64>,
    pub linked_orchestration_id: Option<String>,
    pub linked_turn_id: Option<String>,
}

pub async fn create_task(
    Query(q): Query<CreateTaskQuery>,
    Json(body): Json<TaskCreateBody>,
) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || insert_task(&q.user_id, body))
        .await
        .unwrap_or(None);
    match result {
        Some(task) => (StatusCode::CREATED, Json(json!({"task": task}))),
        None => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"detail": "Failed to create task"})),
        ),
    }
}

fn insert_task(user_id: &str, body: TaskCreateBody) -> Option<Value> {
    let conn = open_tasks_db_rw()?;
    let task_id = format!("task_{}", &uuid::Uuid::new_v4().to_string()[..12]);
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs_f64();
    let description = body.description.unwrap_or_default();
    let priority = body.priority.unwrap_or_else(|| "medium".to_string());
    let tags = body.tags.unwrap_or_default();
    let tags_json = serde_json::to_string(&tags).unwrap_or_else(|_| "[]".to_string());

    conn.execute(
        "INSERT INTO tasks (task_id, title, description, status, priority, tags_json, \
         due_date, created_by, user_id, session_id, linked_orchestration_id, \
         linked_turn_id, created_at, updated_at) \
         VALUES (?1, ?2, ?3, 'open', ?4, ?5, ?6, 'user', ?7, NULL, ?8, ?9, ?10, ?11)",
        rusqlite::params![
            task_id,
            body.title,
            description,
            priority,
            tags_json,
            body.due_date,
            user_id,
            body.linked_orchestration_id,
            body.linked_turn_id,
            now,
            now,
        ],
    )
    .ok()?;
    query_single_task(&task_id)
}

#[derive(Deserialize)]
pub struct TaskUpdateBody {
    pub title: Option<String>,
    pub description: Option<String>,
    pub status: Option<String>,
    pub priority: Option<String>,
    pub tags: Option<Vec<String>>,
    pub due_date: Option<f64>,
    pub linked_orchestration_id: Option<String>,
    pub linked_turn_id: Option<String>,
}

pub async fn update_task(
    Path(task_id): Path<String>,
    Json(body): Json<TaskUpdateBody>,
) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || patch_task(&task_id, body))
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

fn patch_task(task_id: &str, body: TaskUpdateBody) -> Option<Value> {
    let conn = open_tasks_db_rw()?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs_f64();

    let mut sets = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
    let mut idx = 1;

    macro_rules! add_field {
        ($field:expr, $col:expr) => {
            if let Some(val) = $field {
                sets.push(format!("{} = ?{}", $col, idx));
                params.push(Box::new(val));
                idx += 1;
            }
        };
    }

    add_field!(body.title, "title");
    add_field!(body.description, "description");
    add_field!(body.status, "status");
    add_field!(body.priority, "priority");
    if let Some(tags) = body.tags {
        let tags_json = serde_json::to_string(&tags).unwrap_or_else(|_| "[]".to_string());
        sets.push(format!("tags_json = ?{}", idx));
        params.push(Box::new(tags_json));
        idx += 1;
    }
    add_field!(body.due_date, "due_date");
    add_field!(body.linked_orchestration_id, "linked_orchestration_id");
    add_field!(body.linked_turn_id, "linked_turn_id");

    if sets.is_empty() {
        return query_single_task(task_id);
    }

    sets.push(format!("updated_at = ?{}", idx));
    params.push(Box::new(now));
    idx += 1;

    let sql = format!(
        "UPDATE tasks SET {} WHERE task_id = ?{}",
        sets.join(", "),
        idx
    );
    params.push(Box::new(task_id.to_string()));

    let param_refs: Vec<&dyn rusqlite::types::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    conn.execute(&sql, param_refs.as_slice()).ok()?;

    // Read back from read-only to confirm
    query_single_task(task_id)
}

pub async fn delete_task(Path(task_id): Path<String>) -> StatusCode {
    let result = tokio::task::spawn_blocking(move || remove_task(&task_id))
        .await
        .unwrap_or(false);
    if result {
        StatusCode::NO_CONTENT
    } else {
        StatusCode::NOT_FOUND
    }
}

fn remove_task(task_id: &str) -> bool {
    let conn = match open_tasks_db_rw() {
        Some(c) => c,
        None => return false,
    };
    conn.execute(
        "DELETE FROM tasks WHERE task_id = ?1",
        rusqlite::params![task_id],
    )
    .map(|n| n > 0)
    .unwrap_or(false)
}
