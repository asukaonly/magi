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

#[derive(Deserialize)]
pub(in crate::api) struct ActivityQuery {
    pub(in crate::api) limit: Option<i64>,
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
