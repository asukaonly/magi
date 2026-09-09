//! Shared service contracts without desktop, networking, database or runtime dependencies.

use serde::{Deserialize, Serialize};

pub mod config;
pub mod lifecycle;

pub const SERVER_PROTOCOL_VERSION: u32 = 2;

/// Private launch request passed over the owning desktop's stdin pipe.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopBootstrap {
    pub session_token: String,
}

/// Listener announcement returned to the desktop over the service's stdout pipe.
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StartedServer {
    pub base_url: String,
    pub server_pid: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn launch_contract_preserves_wire_names_and_rejects_extra_fields() {
        let request = DesktopBootstrap {
            session_token: "test-launch-token".into(),
        };
        assert_eq!(
            serde_json::to_value(request).unwrap(),
            serde_json::json!({"session_token":"test-launch-token"})
        );
        let announcement: StartedServer = serde_json::from_value(
            serde_json::json!({"baseUrl":"http://127.0.0.1:19080/api","serverPid":42}),
        )
        .unwrap();
        assert_eq!(announcement.server_pid, 42);
        assert_eq!(
            serde_json::to_value(announcement).unwrap(),
            serde_json::json!({"baseUrl":"http://127.0.0.1:19080/api","serverPid":42})
        );
        assert!(serde_json::from_value::<DesktopBootstrap>(
            serde_json::json!({"session_token":"test","extra":true})
        )
        .is_err());
        assert!(serde_json::from_value::<StartedServer>(
            serde_json::json!({"baseUrl":"http://127.0.0.1/api","serverPid":42,"extra":true})
        )
        .is_err());
    }
}
