use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
pub(in crate::api) struct ListSchedulesQuery {
    pub(in crate::api) enabled_only: Option<bool>,
}

#[derive(Deserialize)]
pub(in crate::api) struct ExecutionsQuery {
    pub(in crate::api) limit: Option<i64>,
}

/// Parsed query for `GET /api/schedules/activity`.
///
/// The standard axum `Query<T>` extractor uses `serde_urlencoded`, which
/// overwrites repeated keys instead of collecting them. The frontend sends
/// `?target_types=a&target_types=b&target_types=c`, so we parse from the raw
/// query string by hand to preserve every occurrence.
#[derive(Default)]
pub(in crate::api) struct ActivityFilters {
    pub(in crate::api) limit: i64,
    pub(in crate::api) since: Option<f64>,
    pub(in crate::api) until: Option<f64>,
    pub(in crate::api) target_types: Vec<String>,
    pub(in crate::api) statuses: Vec<String>,
}

impl ActivityFilters {
    pub(in crate::api) fn from_query(raw: Option<&str>) -> Self {
        let mut out = ActivityFilters {
            limit: 100,
            ..Self::default()
        };
        let Some(q) = raw else { return out };
        for (key, value) in form_urlencoded::parse(q.as_bytes()) {
            match key.as_ref() {
                "limit" => {
                    if let Ok(v) = value.parse::<i64>() {
                        out.limit = v.clamp(1, 300);
                    }
                }
                "since" => {
                    if let Ok(v) = value.parse::<f64>() {
                        out.since = Some(v);
                    }
                }
                "until" => {
                    if let Ok(v) = value.parse::<f64>() {
                        out.until = Some(v);
                    }
                }
                "target_types" => out.target_types.push(value.into_owned()),
                "statuses" => out.statuses.push(value.into_owned()),
                _ => {}
            }
        }
        out
    }
}

#[derive(Deserialize)]
pub(in crate::api) struct ActivityCancelBody {
    pub(in crate::api) reason: Option<String>,
}

#[derive(Deserialize)]
pub(in crate::api) struct ScheduleTrigger {
    pub(in crate::api) trigger_type: String,
    pub(in crate::api) config: Value,
}

#[derive(Deserialize)]
pub(in crate::api) struct ScheduleCreateBody {
    pub(in crate::api) schedule_id: String,
    pub(in crate::api) target_type: String,
    pub(in crate::api) target_key: String,
    pub(in crate::api) trigger: ScheduleTrigger,
    pub(in crate::api) target_payload: Option<Value>,
    pub(in crate::api) enabled: Option<bool>,
    pub(in crate::api) metadata: Option<Value>,
}

#[derive(Deserialize)]
pub(in crate::api) struct ScheduleUpdateBody {
    pub(in crate::api) trigger: Option<ScheduleTrigger>,
    pub(in crate::api) target_payload: Option<Value>,
    pub(in crate::api) enabled: Option<bool>,
    pub(in crate::api) metadata: Option<Value>,
}
