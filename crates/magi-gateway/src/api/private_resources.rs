use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use percent_encoding::{utf8_percent_encode, NON_ALPHANUMERIC};
use serde::{Deserialize, Serialize};
use std::path::Path;

use super::state::ApiState;

const MAX_RESOURCE_IDENTIFIER_LENGTH: usize = 2048;

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PrivateResourceRequest {
    ChatAttachment {
        user_id: String,
        session_id: String,
        attachment_id: String,
    },
    TimelineAsset {
        asset_ref: String,
    },
    UserAvatar {
        filename: String,
    },
}

#[derive(Serialize)]
struct PrivateResourceGrant {
    access_url: String,
    expires_at_ms: u64,
}

pub async fn issue_private_resource_ticket(
    State(state): State<ApiState>,
    Json(payload): Json<PrivateResourceRequest>,
) -> Response {
    let path = match protected_path(payload) {
        Some(path) => path,
        None => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "success": false,
                    "message": "Private resource identifier is invalid",
                    "error_code": "invalid_private_resource",
                })),
            )
                .into_response();
        }
    };
    let grant = state.security.issue_resource_ticket(path);
    (
        StatusCode::CREATED,
        Json(serde_json::json!({
            "success": true,
            "message": "Private resource access granted",
            "data": PrivateResourceGrant {
                access_url: grant.access_path,
                expires_at_ms: grant.expires_at_ms,
            },
        })),
    )
        .into_response()
}

fn protected_path(payload: PrivateResourceRequest) -> Option<String> {
    match payload {
        PrivateResourceRequest::ChatAttachment {
            user_id,
            session_id,
            attachment_id,
        } => {
            if !safe_identifier(&user_id)
                || !safe_identifier(&session_id)
                || !safe_identifier(&attachment_id)
            {
                return None;
            }
            let query = form_urlencoded::Serializer::new(String::new())
                .append_pair("user_id", &user_id)
                .finish();
            Some(format!(
                "/api/messages/session/{session_id}/attachments/{attachment_id}/content?{query}"
            ))
        }
        PrivateResourceRequest::TimelineAsset { asset_ref } => {
            let asset_ref = asset_ref.trim();
            if asset_ref.is_empty() || asset_ref.len() > MAX_RESOURCE_IDENTIFIER_LENGTH {
                return None;
            }
            Some(format!(
                "/api/timeline/asset/{}",
                utf8_percent_encode(asset_ref, NON_ALPHANUMERIC)
            ))
        }
        PrivateResourceRequest::UserAvatar { filename } => {
            if !safe_filename(&filename) {
                return None;
            }
            Some(format!(
                "/static/user-avatars/{}",
                utf8_percent_encode(&filename, NON_ALPHANUMERIC)
            ))
        }
    }
}

fn safe_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}

fn safe_filename(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 255
        && value != "."
        && value != ".."
        && Path::new(value).file_name().and_then(|name| name.to_str()) == Some(value)
}

#[cfg(test)]
mod tests {
    use super::{protected_path, PrivateResourceRequest};

    #[test]
    fn private_resource_paths_are_typed_and_normalized() {
        assert_eq!(
            protected_path(PrivateResourceRequest::ChatAttachment {
                user_id: "local_user".to_string(),
                session_id: "session-1".to_string(),
                attachment_id: "attachment_1".to_string(),
            })
            .as_deref(),
            Some(
                "/api/messages/session/session-1/attachments/attachment_1/content?user_id=local_user"
            )
        );
        assert_eq!(
            protected_path(PrivateResourceRequest::TimelineAsset {
                asset_ref: "photo-library://day/IMG 1.jpg".to_string(),
            })
            .as_deref(),
            Some("/api/timeline/asset/photo%2Dlibrary%3A%2F%2Fday%2FIMG%201%2Ejpg")
        );
        assert!(protected_path(PrivateResourceRequest::UserAvatar {
            filename: "../private.png".to_string(),
        })
        .is_none());
    }
}
