use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde_json::{json, Value};

use super::read::{query_single_task, query_tasks};
use super::types::{CreateTaskQuery, ListTasksQuery, TaskCreateBody, TaskUpdateBody};
use super::write::{insert_task, patch_task, remove_task};

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
