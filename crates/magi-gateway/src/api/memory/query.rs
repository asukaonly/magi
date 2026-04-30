use serde::Deserialize;

pub(super) const DEFAULT_LIMIT: i64 = 100;
const MAX_LIMIT: i64 = 500;

// ---------------------------------------------------------------------------
// Query parameter structs
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct L1EventsQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub event_type: Option<String>,
    pub user_id: Option<String>,
    pub session_id: Option<String>,
    pub query: Option<String>,
    pub source: Option<String>,
    pub source_item_id: Option<String>,
    pub idempotency_key: Option<String>,
    pub start_date: Option<String>,
    pub end_date: Option<String>,
}

#[derive(Deserialize)]
pub struct PaginationQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Deserialize)]
pub struct SummariesQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub summary_type: Option<String>,
    pub summary_category: Option<String>,
}

pub(super) fn clamp_limit(limit: Option<i64>, default: i64) -> i64 {
    limit.unwrap_or(default).clamp(1, MAX_LIMIT)
}

pub(super) fn clamp_offset(offset: Option<i64>) -> i64 {
    offset.unwrap_or(0).max(0)
}
