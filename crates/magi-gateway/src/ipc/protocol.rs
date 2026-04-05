//! NDJSON IPC protocol message types.
//!
//! See `docs/gateway-migration-plan.md` § IPC Protocol for the full spec.

use serde::{Deserialize, Serialize};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Rust → Python (outbound)
// ---------------------------------------------------------------------------

/// A request expecting a response (or stream + response).
#[derive(Debug, Serialize)]
pub struct IpcRequest {
    pub id: String,
    pub method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub params: Option<Value>,
}

/// A fire-and-forget notification (no response expected).
#[derive(Debug, Serialize)]
pub struct IpcNotify {
    pub method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub params: Option<Value>,
}

// ---------------------------------------------------------------------------
// Python → Rust (inbound)
// ---------------------------------------------------------------------------

/// Parsed inbound message from Python.
#[derive(Debug)]
pub enum InboundMessage {
    /// Successful response terminating a request.
    Response { id: String, result: Value },
    /// Error response terminating a request.
    Error { id: String, error: IpcError },
    /// Intermediate streaming data for a request.
    Stream { id: String, data: Value },
    /// Unsolicited event pushed by Python runtime.
    Event { event: String, data: Value },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IpcError {
    pub code: i64,
    pub message: String,
}

impl std::fmt::Display for IpcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "IPC error {}: {}", self.code, self.message)
    }
}

impl std::error::Error for IpcError {}

/// Parse a single JSON line from Python into an [`InboundMessage`].
pub fn parse_inbound(line: &str) -> Result<InboundMessage, String> {
    let v: Value = serde_json::from_str(line).map_err(|e| format!("Invalid JSON: {e}"))?;
    let obj = v.as_object().ok_or("Expected JSON object")?;

    // Event (no id)
    if let Some(event) = obj.get("event").and_then(|v| v.as_str()) {
        let data = obj.get("data").cloned().unwrap_or(Value::Null);
        return Ok(InboundMessage::Event {
            event: event.to_string(),
            data,
        });
    }

    // Request-scoped messages (have id)
    let id = obj
        .get("id")
        .and_then(|v| v.as_str())
        .ok_or("Message has neither 'event' nor 'id'")?
        .to_string();

    if let Some(result) = obj.get("result") {
        return Ok(InboundMessage::Response {
            id,
            result: result.clone(),
        });
    }

    if let Some(error) = obj.get("error") {
        let ipc_error: IpcError = serde_json::from_value(error.clone())
            .map_err(|e| format!("Invalid error object: {e}"))?;
        return Ok(InboundMessage::Error {
            id,
            error: ipc_error,
        });
    }

    if let Some(stream_data) = obj.get("stream") {
        return Ok(InboundMessage::Stream {
            id,
            data: stream_data.clone(),
        });
    }

    Err("Unrecognized message shape".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_response() {
        let line = r#"{"id":"abc","result":{"ok":true}}"#;
        match parse_inbound(line).unwrap() {
            InboundMessage::Response { id, result } => {
                assert_eq!(id, "abc");
                assert_eq!(result, serde_json::json!({"ok": true}));
            }
            other => panic!("Expected Response, got {:?}", other),
        }
    }

    #[test]
    fn parse_error() {
        let line = r#"{"id":"def","error":{"code":-1,"message":"boom"}}"#;
        match parse_inbound(line).unwrap() {
            InboundMessage::Error { id, error } => {
                assert_eq!(id, "def");
                assert_eq!(error.code, -1);
                assert_eq!(error.message, "boom");
            }
            other => panic!("Expected Error, got {:?}", other),
        }
    }

    #[test]
    fn parse_stream() {
        let line = r#"{"id":"s1","stream":{"type":"token","text":"hi"}}"#;
        match parse_inbound(line).unwrap() {
            InboundMessage::Stream { id, data } => {
                assert_eq!(id, "s1");
                assert_eq!(data["type"], "token");
            }
            other => panic!("Expected Stream, got {:?}", other),
        }
    }

    #[test]
    fn parse_event() {
        let line = r#"{"event":"agent.status","data":{"status":"running"}}"#;
        match parse_inbound(line).unwrap() {
            InboundMessage::Event { event, data } => {
                assert_eq!(event, "agent.status");
                assert_eq!(data["status"], "running");
            }
            other => panic!("Expected Event, got {:?}", other),
        }
    }
}
