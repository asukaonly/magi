use axum::extract::{Path, Query, RawQuery};
use axum::http::StatusCode;
use axum::Json;
use serde_json::{json, Value};

use super::read::{query_activity, query_executions, query_schedules, query_single_schedule};
use super::types::{
    ActivityCancelBody, ActivityFilters, ExecutionsQuery, ListSchedulesQuery, ScheduleCreateBody,
    ScheduleUpdateBody,
};
use super::write::{cancel_queued_activity, patch_schedule, remove_schedule, upsert_schedule};

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

pub async fn list_activity(RawQuery(raw): RawQuery) -> Json<Value> {
    let filters = ActivityFilters::from_query(raw.as_deref());
    let result = tokio::task::spawn_blocking(move || query_activity(filters))
        .await
        .unwrap_or_else(|_| json!({"activities": []}));
    Json(result)
}

pub async fn cancel_activity(
    Path(activity_id): Path<String>,
    body: Option<Json<ActivityCancelBody>>,
) -> (StatusCode, Json<Value>) {
    let reason = body
        .and_then(|Json(body)| body.reason)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "cancelled_by_user".to_string());
    let result = tokio::task::spawn_blocking(move || cancel_queued_activity(&activity_id, &reason))
        .await
        .unwrap_or(None);
    match result {
        Some(activity) => (StatusCode::OK, Json(json!({"activity": activity}))),
        None => (
            StatusCode::CONFLICT,
            Json(json!({"detail": "Activity is not cancellable"})),
        ),
    }
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
