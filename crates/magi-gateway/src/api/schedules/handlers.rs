use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde_json::{json, Value};

use super::read::{query_executions, query_schedules, query_single_schedule};
use super::types::{ExecutionsQuery, ListSchedulesQuery, ScheduleCreateBody, ScheduleUpdateBody};
use super::write::{patch_schedule, remove_schedule, upsert_schedule};

/// Native GET /api/schedules handler.
pub async fn list_schedules(Query(params): Query<ListSchedulesQuery>) -> Json<Value> {
    let enabled_only = params.enabled_only.unwrap_or(false);
    let result = tokio::task::spawn_blocking(move || query_schedules(enabled_only))
        .await
        .unwrap_or_else(|_| json!({"schedules": []}));
    Json(result)
}

/// Native GET /api/schedules/:schedule_id handler.
pub async fn get_schedule(Path(schedule_id): Path<String>) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || query_single_schedule(&schedule_id))
        .await
        .unwrap_or(None);
    match result {
        Some(v) => (StatusCode::OK, Json(v)),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Schedule not found"})),
        ),
    }
}

/// Native GET /api/schedules/:schedule_id/executions handler.
pub async fn list_schedule_executions(
    Path(schedule_id): Path<String>,
    Query(params): Query<ExecutionsQuery>,
) -> Json<Value> {
    let limit = params.limit.unwrap_or(20).clamp(1, 100);
    let result = tokio::task::spawn_blocking(move || query_executions(Some(&schedule_id), limit))
        .await
        .unwrap_or_else(|_| json!({"executions": []}));
    Json(result)
}

/// Native GET /api/schedules/executions/recent handler.
pub async fn list_recent_executions(Query(params): Query<ExecutionsQuery>) -> Json<Value> {
    let limit = params.limit.unwrap_or(20).clamp(1, 100);
    let result = tokio::task::spawn_blocking(move || query_executions(None, limit))
        .await
        .unwrap_or_else(|_| json!({"executions": []}));
    Json(result)
}

pub async fn create_schedule(Json(body): Json<ScheduleCreateBody>) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || upsert_schedule(body))
        .await
        .unwrap_or(None);
    match result {
        Some(schedule) => (StatusCode::CREATED, Json(json!({"schedule": schedule}))),
        None => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"detail": "Failed to create schedule"})),
        ),
    }
}

pub async fn update_schedule(
    Path(schedule_id): Path<String>,
    Json(body): Json<ScheduleUpdateBody>,
) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || patch_schedule(&schedule_id, body))
        .await
        .unwrap_or(None);
    match result {
        Some(schedule) => (StatusCode::OK, Json(json!({"schedule": schedule}))),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "Schedule not found"})),
        ),
    }
}

pub async fn delete_schedule(Path(schedule_id): Path<String>) -> StatusCode {
    let result = tokio::task::spawn_blocking(move || remove_schedule(&schedule_id))
        .await
        .unwrap_or(false);
    if result {
        StatusCode::NO_CONTENT
    } else {
        StatusCode::NOT_FOUND
    }
}
