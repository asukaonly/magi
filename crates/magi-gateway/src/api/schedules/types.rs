use serde::Deserialize;

#[derive(Deserialize)]
pub(in crate::api) struct ExecutionsQuery {
    pub limit: Option<i64>,
}
