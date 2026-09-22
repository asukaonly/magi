use axum::extract::Query;
use axum::http::StatusCode;
use axum::Json;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::db;

const DEFAULT_USER_ID: &str = "default_user";
const DEFAULT_LIMIT: i64 = 50;
const MAX_LIMIT: i64 = 200;

type PageKey = (i64, i64, String);
type PageCursor = (u8, Vec<String>, String, PageKey);

#[derive(Default, Deserialize)]
pub struct SessionsQuery {
    pub user_id: Option<String>,
    pub limit: Option<i64>,
    pub before: Option<String>,
    pub known_revision: Option<String>,
}

#[derive(Debug)]
enum SessionReadError {
    Storage,
    InvalidCursor,
    StaleCursor,
    InvalidLimit,
}

impl From<rusqlite::Error> for SessionReadError {
    fn from(_: rusqlite::Error) -> Self {
        Self::Storage
    }
}

/// Read a bounded, revision-bound session page from the sidecar-owned database.
pub async fn list_sessions(Query(params): Query<SessionsQuery>) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || {
        let mut conn =
            Connection::open_with_flags(db::chat_db_path(), OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        query_session_page(&mut conn, params)
    })
    .await;
    match result {
        Ok(Ok(value)) => (StatusCode::OK, Json(value)),
        Ok(Err(SessionReadError::InvalidCursor)) => (
            StatusCode::BAD_REQUEST,
            Json(
                json!({"detail": {"code":"invalid_page_cursor", "message":"Invalid chat page cursor"}}),
            ),
        ),
        Ok(Err(SessionReadError::StaleCursor)) => (
            StatusCode::CONFLICT,
            Json(
                json!({"detail": {"code":"stale_page_cursor", "message":"Chat page snapshot changed"}}),
            ),
        ),
        Ok(Err(SessionReadError::InvalidLimit)) => (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({"detail":"Session page limit must be between 1 and 200"})),
        ),
        _ => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"detail": "Conversation sessions unavailable"})),
        ),
    }
}

fn decode_cursor(
    value: &str,
    scope: &[String],
    revision: &str,
) -> Result<PageKey, SessionReadError> {
    if value.is_empty() || value.len() > 4096 {
        return Err(SessionReadError::InvalidCursor);
    }
    let bytes = URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| SessionReadError::InvalidCursor)?;
    let (version, cursor_scope, cursor_revision, key): PageCursor =
        serde_json::from_slice(&bytes).map_err(|_| SessionReadError::InvalidCursor)?;
    if version != 1 || cursor_scope != scope || key.2.is_empty() {
        return Err(SessionReadError::InvalidCursor);
    }
    if cursor_revision != revision {
        return Err(SessionReadError::StaleCursor);
    }
    Ok(key)
}

fn query_session_page(
    conn: &mut Connection,
    params: SessionsQuery,
) -> Result<Value, SessionReadError> {
    let user_id = params.user_id.as_deref().unwrap_or(DEFAULT_USER_ID);
    let limit = params.limit.unwrap_or(DEFAULT_LIMIT);
    if !(1..=MAX_LIMIT).contains(&limit) {
        return Err(SessionReadError::InvalidLimit);
    }
    if params
        .known_revision
        .as_ref()
        .is_some_and(|value| value.is_empty() || value.len() > 128)
    {
        return Err(SessionReadError::InvalidCursor);
    }
    let tx = conn.transaction()?;
    let revision = tx
        .query_row(
            "SELECT epoch || ':' || revision FROM chat_read_revisions WHERE user_id = ?1 AND scope = ''",
            [user_id],
            |row| row.get::<_, String>(0),
        )
        .optional()?
        .unwrap_or_else(|| "empty:0".into());
    let scope = vec!["sessions".into(), user_id.into()];
    let boundary = params
        .before
        .as_deref()
        .map(|cursor| decode_cursor(cursor, &scope, &revision))
        .transpose()?;
    if params.before.is_none() && params.known_revision.as_deref() == Some(&revision) {
        return Ok(json!({
            "user_id":user_id,"sessions":[],"count":0,"revision":revision,
            "not_modified":true,"has_more":false,"next_before":null
        }));
    }
    let mut sql = String::from(
        "SELECT session_id, title, title_overridden, last_message_preview, \
                last_user_message_preview, workspace_path, updated_at_ms, \
                last_message_at_ms, message_count, history_version, created_at_ms \
         FROM chat_sessions \
         WHERE user_id = ? \
           AND deleted_at_ms IS NULL \
           AND archived_at_ms IS NULL",
    );
    let mut values: Vec<rusqlite::types::Value> = vec![user_id.to_owned().into()];
    if let Some((updated, created, id)) = boundary {
        sql.push_str(" AND (updated_at_ms, created_at_ms, session_id) < (?, ?, ?)");
        values.extend([updated.into(), created.into(), id.into()]);
    }
    sql.push_str(" ORDER BY updated_at_ms DESC, created_at_ms DESC, session_id DESC LIMIT ?");
    values.push((limit + 1).into());
    let mut stmt = tx.prepare(&sql)?;
    let mut rows: Vec<(Value, PageKey)> = stmt
        .query_map(rusqlite::params_from_iter(values), |row| {
            let updated_at_ms: i64 = row.get(6)?;
            let last_message_at_ms: Option<i64> = row.get(7)?;
            let session_id: String = row.get(0)?;
            let key = (updated_at_ms, row.get(10)?, session_id.clone());
            Ok((
                json!({
                    "session_id":session_id,"title":row.get::<_,String>(1)?,
                    "title_overridden":row.get::<_,bool>(2)?,
                    "last_message_preview":row.get::<_,String>(3)?,
                    "last_user_message_preview":row.get::<_,String>(4)?,
                    "workspace_path":row.get::<_,Option<String>>(5)?,
                    "last_timestamp":last_message_at_ms.unwrap_or(updated_at_ms),
                    "message_count":row.get::<_,i64>(8)?,
                    "history_version":row.get::<_,i64>(9)?
                }),
                key,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let has_more = rows.len() > limit as usize;
    rows.truncate(limit as usize);
    let next_before = if has_more {
        rows.last().map(|(_, key)| {
            URL_SAFE_NO_PAD.encode(
                serde_json::to_vec(&(1, &scope, &revision, key))
                    .expect("Page cursor is serializable"),
            )
        })
    } else {
        None
    };
    let sessions: Vec<Value> = rows.into_iter().map(|(value, _)| value).collect();
    Ok(json!({
        "user_id":user_id,"count":sessions.len(),"sessions":sessions,"revision":revision,
        "not_modified":false,"has_more":has_more,"next_before":next_before
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seeded_connection() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE chat_read_revisions(user_id TEXT,scope TEXT,epoch TEXT,revision INTEGER);
             INSERT INTO chat_read_revisions VALUES ('user','', 'epoch', 1);
             CREATE TABLE chat_sessions(session_id TEXT,user_id TEXT,title TEXT,title_overridden INTEGER,
                last_message_preview TEXT,last_user_message_preview TEXT,workspace_path TEXT,
                updated_at_ms INTEGER,last_message_at_ms INTEGER,message_count INTEGER,history_version INTEGER,
                created_at_ms INTEGER,deleted_at_ms INTEGER,archived_at_ms INTEGER);",
        ).unwrap();
        for i in 0..205 {
            conn.execute("INSERT INTO chat_sessions VALUES (?1,'user','Chat',0,'Hi','Hi',NULL,1,NULL,1,1,1,NULL,NULL)",
                [format!("session-{i:03}")]).unwrap();
        }
        conn
    }

    #[test]
    fn keyset_pages_cover_equal_timestamps_and_support_conditional_reads() {
        let mut conn = seeded_connection();
        let mut before = None;
        let mut ids = Vec::new();
        loop {
            let page = query_session_page(
                &mut conn,
                SessionsQuery {
                    user_id: Some("user".into()),
                    limit: Some(50),
                    before,
                    known_revision: None,
                },
            )
            .unwrap();
            ids.extend(
                page["sessions"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|s| s["session_id"].as_str().unwrap().to_owned()),
            );
            if !page["has_more"].as_bool().unwrap() {
                break;
            }
            before = Some(page["next_before"].as_str().unwrap().to_owned());
        }
        assert_eq!(ids.len(), 205);
        assert_eq!(ids.first().unwrap(), "session-204");
        assert_eq!(ids.last().unwrap(), "session-000");
        ids.sort();
        ids.dedup();
        assert_eq!(ids.len(), 205);
        let unchanged = query_session_page(
            &mut conn,
            SessionsQuery {
                user_id: Some("user".into()),
                known_revision: Some("epoch:1".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(unchanged["not_modified"], true);
        assert_eq!(unchanged["count"], 0);
    }

    #[test]
    fn cursors_reject_another_owner_and_a_changed_snapshot() {
        let mut conn = seeded_connection();
        let first = query_session_page(
            &mut conn,
            SessionsQuery {
                user_id: Some("user".into()),
                limit: Some(1),
                ..Default::default()
            },
        )
        .unwrap();
        let cursor = first["next_before"].as_str().unwrap().to_owned();
        assert!(matches!(
            query_session_page(
                &mut conn,
                SessionsQuery {
                    user_id: Some("other".into()),
                    before: Some(cursor.clone()),
                    ..Default::default()
                }
            ),
            Err(SessionReadError::InvalidCursor)
        ));
        conn.execute("UPDATE chat_read_revisions SET revision=2", [])
            .unwrap();
        assert!(matches!(
            query_session_page(
                &mut conn,
                SessionsQuery {
                    user_id: Some("user".into()),
                    before: Some(cursor),
                    ..Default::default()
                }
            ),
            Err(SessionReadError::StaleCursor)
        ));
    }
}
