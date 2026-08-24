use serde::Deserialize;

#[derive(Deserialize)]
pub(in crate::api) struct ListTasksQuery {
    pub(in crate::api) user_id: String,
    pub(in crate::api) status: Option<String>,
    pub(in crate::api) limit: Option<i64>,
    pub(in crate::api) offset: Option<i64>,
}

#[derive(Deserialize)]
pub(in crate::api) struct CreateTaskQuery {
    pub(in crate::api) user_id: String,
}

#[derive(Deserialize)]
pub(in crate::api) struct TaskCreateBody {
    pub(in crate::api) title: String,
    pub(in crate::api) description: Option<String>,
    pub(in crate::api) priority: Option<String>,
    pub(in crate::api) tags: Option<Vec<String>>,
    pub(in crate::api) due_date: Option<f64>,
    pub(in crate::api) linked_turn_id: Option<String>,
}

#[derive(Deserialize)]
pub(in crate::api) struct TaskUpdateBody {
    pub(in crate::api) title: Option<String>,
    pub(in crate::api) description: Option<String>,
    pub(in crate::api) status: Option<String>,
    pub(in crate::api) priority: Option<String>,
    pub(in crate::api) tags: Option<Vec<String>>,
    pub(in crate::api) due_date: Option<f64>,
    pub(in crate::api) linked_turn_id: Option<String>,
}
