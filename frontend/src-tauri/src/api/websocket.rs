use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Query, State};
use axum::response::IntoResponse;
use futures::sink::SinkExt;
use futures::stream::StreamExt;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::sync::Arc;
use tokio::sync::Mutex;

use super::state::ApiState;

#[derive(Deserialize)]
pub struct WsQuery {
    #[serde(default)]
    pub token: String,
}

/// GET /ws — WebSocket upgrade handler
pub async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<ApiState>,
    Query(_params): Query<WsQuery>,
) -> impl IntoResponse {
    // Token validation could be added here if needed
    ws.on_upgrade(move |socket| handle_ws_connection(socket, state))
}

/// Per-connection state
struct WsConnection {
    rooms: HashSet<String>,
}

async fn handle_ws_connection(socket: WebSocket, state: ApiState) {
    let (ws_sender, mut ws_receiver) = socket.split();
    let ws_sender = Arc::new(Mutex::new(ws_sender));
    let conn_state = Arc::new(Mutex::new(WsConnection {
        rooms: HashSet::new(),
    }));

    // Subscribe to broadcast channel for notifications
    let mut broadcast_rx = state.ws_broadcast.subscribe();
    let sender_for_broadcast = ws_sender.clone();
    let conn_for_broadcast = conn_state.clone();

    // Task: forward broadcast notifications to this WS client (filtered by room)
    let broadcast_task = tokio::spawn(async move {
        loop {
            match broadcast_rx.recv().await {
                Ok(msg) => {
                    let rooms = conn_for_broadcast.lock().await;
                    let room_key = format!("user_{}", msg.user_id);
                    if !rooms.rooms.contains(&room_key) {
                        continue;
                    }
                    drop(rooms);

                    let payload = json!({
                        "event": msg.event,
                        "data": msg.data,
                    });
                    let text = serde_json::to_string(&payload).unwrap_or_default();
                    let mut sender = sender_for_broadcast.lock().await;
                    if sender.send(Message::Text(text.into())).await.is_err() {
                        break;
                    }
                }
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                    continue;
                }
                Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
            }
        }
    });

    // Task: handle incoming WS messages
    let sender_for_recv = ws_sender.clone();
    let conn_for_recv = conn_state.clone();
    let recv_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = ws_receiver.next().await {
            match msg {
                Message::Text(text) => {
                    let data: Value = match serde_json::from_str(&text) {
                        Ok(v) => v,
                        Err(_) => continue,
                    };
                    let response =
                        handle_ws_message(&data, &state, &conn_for_recv).await;
                    if let Some(resp) = response {
                        let text = serde_json::to_string(&resp).unwrap_or_default();
                        let mut sender = sender_for_recv.lock().await;
                        if sender.send(Message::Text(text.into())).await.is_err() {
                            break;
                        }
                    }
                }
                Message::Close(_) => break,
                _ => {}
            }
        }
    });

    // Wait for either task to finish, then abort the other
    tokio::select! {
        _ = broadcast_task => {}
        _ = recv_task => {}
    }
}

async fn handle_ws_message(
    data: &Value,
    state: &ApiState,
    conn: &Arc<Mutex<WsConnection>>,
) -> Option<Value> {
    let msg_type = data.get("type").and_then(|v| v.as_str()).unwrap_or("");
    match msg_type {
        "subscribe" => {
            let channel = data.get("channel").and_then(|v| v.as_str()).unwrap_or("");
            if channel.is_empty() {
                return Some(json!({"type": "error", "message": "Channel is required for subscription"}));
            }
            conn.lock().await.rooms.insert(channel.to_string());
            Some(json!({"type": "subscribed", "channel": channel}))
        }
        "unsubscribe" => {
            let channel = data.get("channel").and_then(|v| v.as_str()).unwrap_or("");
            if channel.is_empty() {
                return Some(json!({"type": "error", "message": "Channel is required for unsubscription"}));
            }
            conn.lock().await.rooms.remove(channel);
            Some(json!({"type": "unsubscribed", "channel": channel}))
        }
        "ping" => Some(json!({"type": "pong"})),
        "send_message" => handle_send_message(data, state).await,
        "get_history" => handle_get_history(data).await,
        "get_personality" => handle_get_personality().await,
        _ => Some(json!({"type": "error", "message": format!("Unknown message type: {msg_type}")})),
    }
}

/// Forward send_message to Python via IPC api.forward (POST /api/messages/send)
async fn handle_send_message(data: &Value, state: &ApiState) -> Option<Value> {
    let ipc = match &state.ipc_client {
        Some(c) => c.clone(),
        None => {
            return Some(json!({"type": "error", "message": "Backend not connected"}));
        }
    };

    // Build the payload matching the REST API's UserMessageRequest
    let body = json!({
        "user_id": data.get("user_id").and_then(|v| v.as_str()).unwrap_or("default_user"),
        "session_id": data.get("session_id"),
        "message": data.get("message").and_then(|v| v.as_str()).unwrap_or(""),
        "attachments": data.get("attachments").cloned().unwrap_or(json!([])),
        "reply_to_message_id": data.get("reply_to_message_id"),
        "workspace_path": data.get("workspace_path"),
        "client_turn_id": data.get("client_turn_id"),
        "metadata": data.get("metadata").cloned().unwrap_or(json!({})),
    });

    let params = json!({
        "method": "POST",
        "path": "/api/messages/send",
        "body": serde_json::to_string(&body).unwrap_or_default(),
        "headers": {"content-type": "application/json"},
    });

    match ipc.request("api.forward", Some(params)).await {
        Ok(result) => {
            // Parse the forwarded response body
            if let Some(body_str) = result.get("body").and_then(|v| v.as_str()) {
                if let Ok(parsed) = serde_json::from_str::<Value>(body_str) {
                    let success = parsed.get("success").and_then(|v| v.as_bool()).unwrap_or(false);
                    if success {
                        let resp_data = parsed.get("data").cloned().unwrap_or(json!({}));
                        return Some(json!({
                            "type": "message_sent",
                            "data": resp_data,
                        }));
                    } else {
                        let msg = parsed
                            .get("message")
                            .or_else(|| parsed.get("detail"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("Failed to send message");
                        return Some(json!({"type": "error", "message": msg}));
                    }
                }
            }
            Some(json!({"type": "error", "message": "Invalid response from backend"}))
        }
        Err(e) => Some(json!({"type": "error", "message": format!("IPC error: {e}")})),
    }
}

/// Handle get_history directly from Rust DB
async fn handle_get_history(data: &Value) -> Option<Value> {
    let session_id = data
        .get("session_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let user_id = data
        .get("user_id")
        .and_then(|v| v.as_str())
        .unwrap_or("default_user")
        .to_string();

    if session_id.is_empty() {
        return Some(json!({"type": "error", "message": "Session ID is required"}));
    }

    let result = tokio::task::spawn_blocking(move || {
        super::messages::query_history("default_user", &session_id)
    })
    .await
    .ok()?;

    Some(json!({
        "type": "history",
        "data": {
            "user_id": user_id,
            "session_id": data.get("session_id"),
            "messages": result.get("messages").cloned().unwrap_or(json!([])),
            "count": result.get("messages").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
        }
    }))
}

/// Handle get_personality directly from Rust filesystem
async fn handle_get_personality() -> Option<Value> {
    let result = tokio::task::spawn_blocking(|| {
        let name = super::personality::read_current_name();
        match super::personality::load_personality_json(&name) {
            Ok(mut data) => {
                super::personality::normalize_avatar(&mut data);
                let persona_name = data
                    .pointer("/persona_entity/basic_profile/name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("AI Assistant")
                    .to_string();
                let avatar = data
                    .pointer("/persona_entity/basic_profile/avatar")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let greetings: Vec<String> = data
                    .pointer("/cached_phrases/on_wake")
                    .and_then(|v| v.as_array())
                    .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
                    .unwrap_or_default();
                let greetings = if greetings.is_empty() {
                    data.pointer("/cached_phrases/on_init")
                        .and_then(|v| v.as_array())
                        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect::<Vec<_>>())
                        .unwrap_or_default()
                } else {
                    greetings
                };
                let greeting = if greetings.is_empty() {
                    format!("Hello, I am {persona_name}.")
                } else {
                    let idx = std::time::SystemTime::now()
                        .duration_since(std::time::SystemTime::UNIX_EPOCH)
                        .map(|d| d.as_nanos() as usize)
                        .unwrap_or(0) % greetings.len();
                    greetings[idx].clone()
                };
                json!({
                    "type": "personality_info",
                    "data": {
                        "name": persona_name,
                        "avatar": avatar,
                        "greeting": greeting,
                    }
                })
            }
            Err(_) => json!({
                "type": "personality_info",
                "data": {
                    "name": "AI Assistant",
                    "avatar": "",
                    "greeting": "Hello, I am AI Assistant.",
                }
            }),
        }
    })
    .await
    .ok()?;
    Some(result)
}
