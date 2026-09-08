//! IPC client for communicating with the Python worker over NDJSON.
//!
//! The client maintains a single persistent connection. Requests are multiplexed
//! by UUID. Stream and event messages are dispatched to registered receivers.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::Value;
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncWrite, AsyncWriteExt, BufReader};
use tokio::sync::{mpsc, oneshot, watch};

use super::protocol::{self, InboundMessage, IpcError, IpcNotify, IpcRequest};

/// Default ceiling on how long a single IPC request may wait for the Python
/// worker to respond. This is a hang-protection bound — not a snappy SLO.
/// Legitimate long operations (non-streaming LLM calls, attachment ingest)
/// can take a couple of minutes; we err on the side of "wait, but not
/// forever". Override via the `MAGI_IPC_REQUEST_TIMEOUT_SECS` env var.
const DEFAULT_REQUEST_TIMEOUT_SECS: u64 = 300;
const IPC_AUTH_TIMEOUT: Duration = Duration::from_secs(3);
const IPC_AUTH_METHOD: &str = "ipc.authenticate";

fn default_request_timeout() -> Duration {
    let secs = std::env::var("MAGI_IPC_REQUEST_TIMEOUT_SECS")
        .ok()
        .and_then(|raw| raw.parse::<u64>().ok())
        .filter(|secs| *secs > 0)
        .unwrap_or(DEFAULT_REQUEST_TIMEOUT_SECS);
    Duration::from_secs(secs)
}

/// Envelope returned to a request caller.
#[derive(Debug)]
pub enum ResponseEnvelope {
    Result(Value),
    Error(IpcError),
}

/// Pending request slot waiting for response.
struct PendingRequest {
    tx: oneshot::Sender<ResponseEnvelope>,
}

type PendingMap = HashMap<String, PendingRequest>;

struct PendingGuard {
    id: String,
    pending: Arc<Mutex<PendingMap>>,
}

impl Drop for PendingGuard {
    fn drop(&mut self) {
        self.pending
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(&self.id);
    }
}

/// IPC client connected to the Python worker.
#[derive(Clone)]
pub struct IpcClient {
    /// Serialised write access to the socket.
    write_tx: mpsc::Sender<String>,
    /// In-flight request map (shared with the read loop).
    pending: Arc<Mutex<PendingMap>>,
    closed: watch::Sender<bool>,
}

impl IpcClient {
    /// Connect to the IPC socket at `path` (Unix) and spawn the read/write loops.
    /// Returns the client handle and an event receiver for unsolicited events.
    #[cfg(unix)]
    pub async fn connect(
        path: &str,
        auth_token: &str,
    ) -> Result<(Self, mpsc::Receiver<(String, Value)>), String> {
        let stream = tokio::net::UnixStream::connect(path)
            .await
            .map_err(|e| format!("IPC connect failed: {e}"))?;
        let (reader, writer) = stream.into_split();
        let mut reader = BufReader::new(reader);
        let mut writer = writer;
        Self::authenticate(&mut reader, &mut writer, auth_token).await?;
        Self::start(reader, writer)
    }

    /// Connect to the IPC socket via TCP loopback (Windows fallback).
    #[cfg(not(unix))]
    pub async fn connect(
        addr: &str,
        auth_token: &str,
    ) -> Result<(Self, mpsc::Receiver<(String, Value)>), String> {
        let stream = tokio::net::TcpStream::connect(addr)
            .await
            .map_err(|e| format!("IPC connect failed: {e}"))?;
        let (reader, writer) = stream.into_split();
        let mut reader = BufReader::new(reader);
        let mut writer = writer;
        Self::authenticate(&mut reader, &mut writer, auth_token).await?;
        Self::start(reader, writer)
    }

    async fn authenticate<R, W>(
        reader: &mut R,
        writer: &mut W,
        auth_token: &str,
    ) -> Result<(), String>
    where
        R: AsyncBufRead + Unpin,
        W: AsyncWrite + Unpin,
    {
        if auth_token.trim().is_empty() {
            return Err("IPC authentication failed".to_string());
        }

        let id = uuid::Uuid::new_v4().to_string();
        let request = IpcRequest {
            id: id.clone(),
            method: IPC_AUTH_METHOD.to_string(),
            params: Some(serde_json::json!({"token": auth_token})),
        };
        let mut line =
            serde_json::to_string(&request).map_err(|_| "IPC authentication failed".to_string())?;
        line.push('\n');

        writer
            .write_all(line.as_bytes())
            .await
            .map_err(|_| "IPC authentication failed".to_string())?;
        writer
            .flush()
            .await
            .map_err(|_| "IPC authentication failed".to_string())?;

        let mut response_line = String::new();
        let bytes_read =
            tokio::time::timeout(IPC_AUTH_TIMEOUT, reader.read_line(&mut response_line))
                .await
                .map_err(|_| "IPC authentication failed".to_string())?
                .map_err(|_| "IPC authentication failed".to_string())?;
        if bytes_read == 0 {
            return Err("IPC authentication failed".to_string());
        }

        match protocol::parse_inbound(response_line.trim()) {
            Ok(InboundMessage::Response {
                id: response_id,
                result,
            }) if response_id == id
                && result.get("authenticated").and_then(Value::as_bool) == Some(true) =>
            {
                Ok(())
            }
            _ => Err("IPC authentication failed".to_string()),
        }
    }

    fn start<R, W>(
        reader: BufReader<R>,
        writer: W,
    ) -> Result<(Self, mpsc::Receiver<(String, Value)>), String>
    where
        R: tokio::io::AsyncRead + Unpin + Send + 'static,
        W: tokio::io::AsyncWrite + Unpin + Send + 'static,
    {
        let pending: Arc<Mutex<PendingMap>> = Arc::new(Mutex::new(HashMap::new()));
        let (write_tx, write_rx) = mpsc::channel::<String>(256);
        let (event_tx, event_rx) = mpsc::channel::<(String, Value)>(256);

        let (closed, mut shutdown) = watch::channel(false);
        let connection_closed = closed.clone();
        let read_pending = Arc::clone(&pending);
        tokio::spawn(async move {
            tokio::select! {
                _ = shutdown.changed() => {},
                _ = Self::write_loop(writer, write_rx) => {},
                _ = Self::read_loop(reader, Arc::clone(&read_pending), event_tx) => {},
            }
            connection_closed.send_replace(true);
            read_pending
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .clear();
        });

        Ok((
            Self {
                write_tx,
                pending,
                closed,
            },
            event_rx,
        ))
    }

    /// Close both socket halves and fail pending requests without replaying them.
    pub fn disconnect(&self) {
        self.closed.send_replace(true);
    }

    pub fn is_connected(&self) -> bool {
        !*self.closed.borrow()
    }

    /// Send a fire-and-forget notification.
    pub async fn notify(&self, method: &str, params: Option<Value>) -> Result<(), String> {
        let msg = IpcNotify {
            method: method.to_string(),
            params,
        };
        let mut line = serde_json::to_string(&msg).map_err(|e| format!("Serialize error: {e}"))?;
        line.push('\n');
        self.write_tx
            .send(line)
            .await
            .map_err(|_| "IPC write channel closed".to_string())
    }

    /// Send a request and wait for the response using the default timeout.
    pub async fn request(&self, method: &str, params: Option<Value>) -> Result<Value, IpcError> {
        self.request_with_timeout(method, params, default_request_timeout())
            .await
    }

    /// Send a request and wait for the response with an explicit timeout.
    ///
    /// On timeout the request slot is removed from the pending map so the
    /// memory and oneshot are released. If the worker eventually replies, the
    /// read loop simply finds no pending slot and drops the response.
    pub async fn request_with_timeout(
        &self,
        method: &str,
        params: Option<Value>,
        timeout: Duration,
    ) -> Result<Value, IpcError> {
        let mut closed = self.closed.subscribe();
        if *closed.borrow() {
            return Err(connection_closed_error());
        }
        let id = uuid::Uuid::new_v4().to_string();
        let (tx, rx) = oneshot::channel();
        self.pending
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(id.clone(), PendingRequest { tx });
        let _pending_guard = PendingGuard {
            id: id.clone(),
            pending: Arc::clone(&self.pending),
        };

        let msg = IpcRequest {
            id: id.clone(),
            method: method.to_string(),
            params,
        };
        let mut line = match serde_json::to_string(&msg) {
            Ok(s) => s,
            Err(e) => {
                return Err(IpcError {
                    code: -1,
                    message: format!("Failed to serialise IPC request: {e}"),
                });
            }
        };
        line.push('\n');

        let response = async {
            self.write_tx.send(line).await.map_err(|_| ())?;
            rx.await.map_err(|_| ())
        };
        let result = tokio::select! {
            biased;
            result = tokio::time::timeout(timeout, response) => result,
            _ = closed.changed() => return Err(connection_closed_error()),
        };
        match result {
            Ok(Ok(ResponseEnvelope::Result(v))) => Ok(v),
            Ok(Ok(ResponseEnvelope::Error(e))) => Err(e),
            Ok(Err(_)) => Err(IpcError {
                code: -3,
                message: "Request dropped (connection closed)".to_string(),
            }),
            Err(_) => {
                // Timed out: reclaim the pending slot. A late response will be
                // dropped by the read loop because the slot is gone.
                Err(IpcError {
                    code: -5,
                    message: format!("IPC request timed out after {}s", timeout.as_secs()),
                })
            }
        }
    }

    // ---- Internal loops ----

    async fn write_loop<W: tokio::io::AsyncWrite + Unpin>(
        mut writer: W,
        mut rx: mpsc::Receiver<String>,
    ) {
        while let Some(line) = rx.recv().await {
            if writer.write_all(line.as_bytes()).await.is_err() {
                break;
            }
            if writer.flush().await.is_err() {
                break;
            }
        }
    }

    async fn read_loop<R: tokio::io::AsyncRead + Unpin>(
        reader: BufReader<R>,
        pending: Arc<Mutex<PendingMap>>,
        event_tx: mpsc::Sender<(String, Value)>,
    ) {
        let mut lines = reader.lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let line = line.trim().to_string();
            if line.is_empty() {
                continue;
            }
            let msg = match protocol::parse_inbound(&line) {
                Ok(m) => m,
                Err(_) => continue,
            };
            match msg {
                InboundMessage::Response { id, result } => {
                    let mut map = pending.lock().unwrap_or_else(|e| e.into_inner());
                    if let Some(req) = map.remove(&id) {
                        let _ = req.tx.send(ResponseEnvelope::Result(result));
                    }
                }
                InboundMessage::Error { id, error } => {
                    let mut map = pending.lock().unwrap_or_else(|e| e.into_inner());
                    if let Some(req) = map.remove(&id) {
                        let _ = req.tx.send(ResponseEnvelope::Error(error));
                    }
                }
                InboundMessage::Stream { id: _, data: _ } => {
                    // TODO: Stream relay for Phase 8 (LLM token streaming)
                }
                InboundMessage::Event { event, data } => {
                    let _ = event_tx.send((event, data)).await;
                }
            }
        }
    }
}

fn connection_closed_error() -> IpcError {
    IpcError {
        code: -4,
        message: "IPC connection closed; operation outcome may be unknown".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{duplex, split};

    #[tokio::test]
    async fn completed_response_survives_worker_eof() {
        let (stream, worker) = duplex(4096);
        let (reader, writer) = split(stream);
        let (client, _events) = IpcClient::start(BufReader::new(reader), writer).unwrap();
        let worker_task = tokio::spawn(async move {
            let (reader, mut writer) = split(worker);
            let line = BufReader::new(reader)
                .lines()
                .next_line()
                .await
                .unwrap()
                .unwrap();
            let request: Value = serde_json::from_str(&line).unwrap();
            let response = serde_json::json!({"id": request["id"], "result": "committed"});
            writer
                .write_all(format!("{response}\n").as_bytes())
                .await
                .unwrap();
        });
        assert_eq!(client.request("commit", None).await.unwrap(), "committed");
        worker_task.await.unwrap();
    }

    #[tokio::test]
    async fn replacing_worker_fails_old_request_without_replaying_it() {
        let (old_stream, old_worker) = duplex(4096);
        let (reader, writer) = split(old_stream);
        let (old_client, _events) = IpcClient::start(BufReader::new(reader), writer).unwrap();
        let connection = Arc::new(crate::ipc::RuntimeConnection::connected(Arc::new(
            old_client,
        )));
        let (received_tx, received_rx) = oneshot::channel();
        let old_worker_task = tokio::spawn(async move {
            let mut reader = BufReader::new(old_worker);
            let mut line = String::new();
            reader.read_line(&mut line).await.unwrap();
            received_tx.send(()).unwrap();
            line.clear();
            assert_eq!(reader.read_line(&mut line).await.unwrap(), 0);
        });
        let old_request = {
            let connection = Arc::clone(&connection);
            tokio::spawn(async move {
                connection
                    .request_with_timeout("task.create", None, Duration::from_secs(30))
                    .await
            })
        };
        received_rx.await.unwrap();

        let (new_stream, new_worker) = duplex(4096);
        let (reader, writer) = split(new_stream);
        let (new_client, _events) = IpcClient::start(BufReader::new(reader), writer).unwrap();
        assert_eq!(connection.replace(Some(Arc::new(new_client))), 2);
        assert!(tokio::time::timeout(Duration::from_secs(1), old_request)
            .await
            .unwrap()
            .unwrap()
            .is_err());
        old_worker_task.await.unwrap();

        let new_worker_task = tokio::spawn(async move {
            let (reader, mut writer) = split(new_worker);
            let mut lines = BufReader::new(reader).lines();
            let request: Value =
                serde_json::from_str(&lines.next_line().await.unwrap().unwrap()).unwrap();
            assert_eq!(request["method"], "runtime.ready");
            let response = serde_json::json!({"id": request["id"], "result": {"ready": true}});
            writer
                .write_all(format!("{response}\n").as_bytes())
                .await
                .unwrap();
            // Keep the new worker connected until the owner explicitly disconnects.
            assert!(lines.next_line().await.unwrap().is_none());
        });
        let result = connection
            .request_with_timeout("runtime.ready", None, Duration::from_secs(1))
            .await
            .unwrap();
        assert_eq!(result["ready"], true);
        connection.replace(None);
        assert!(connection.current().is_err());
        new_worker_task.await.unwrap();
    }

    #[tokio::test]
    async fn cancelled_request_releases_its_pending_slot() {
        let (stream, worker) = duplex(4096);
        let (reader, writer) = split(stream);
        let (client, _events) = IpcClient::start(BufReader::new(reader), writer).unwrap();
        let request = {
            let client = client.clone();
            tokio::spawn(async move { client.request("wait", None).await })
        };
        let mut reader = BufReader::new(worker);
        reader.read_line(&mut String::new()).await.unwrap();
        request.abort();
        let _ = request.await;
        assert!(client.pending.lock().unwrap().is_empty());
        client.disconnect();
        assert!(client.request("later", None).await.is_err());
    }

    #[tokio::test]
    async fn authentication_sends_the_credential_as_the_first_frame() {
        let (client_stream, server_stream) = duplex(4096);
        let server = tokio::spawn(async move {
            let (reader, mut writer) = split(server_stream);
            let mut lines = BufReader::new(reader).lines();
            let line = lines.next_line().await.unwrap().unwrap();
            let request: Value = serde_json::from_str(&line).unwrap();
            assert_eq!(request["method"], IPC_AUTH_METHOD);
            assert_eq!(request["params"]["token"], "internal-secret");

            let response = serde_json::json!({
                "id": request["id"],
                "result": {"authenticated": true},
            });
            writer
                .write_all(format!("{response}\n").as_bytes())
                .await
                .unwrap();
            writer.flush().await.unwrap();
        });

        let (reader, mut writer) = split(client_stream);
        let mut reader = BufReader::new(reader);
        IpcClient::authenticate(&mut reader, &mut writer, "internal-secret")
            .await
            .unwrap();
        server.await.unwrap();
    }

    #[tokio::test]
    async fn authentication_rejects_an_error_response() {
        let (client_stream, server_stream) = duplex(4096);
        let server = tokio::spawn(async move {
            let (reader, mut writer) = split(server_stream);
            let mut lines = BufReader::new(reader).lines();
            let line = lines.next_line().await.unwrap().unwrap();
            let request: Value = serde_json::from_str(&line).unwrap();
            let response = serde_json::json!({
                "id": request["id"],
                "error": {"code": -1, "message": "denied"},
            });
            writer
                .write_all(format!("{response}\n").as_bytes())
                .await
                .unwrap();
            writer.flush().await.unwrap();
        });

        let (reader, mut writer) = split(client_stream);
        let mut reader = BufReader::new(reader);
        let error = IpcClient::authenticate(&mut reader, &mut writer, "wrong-secret")
            .await
            .unwrap_err();
        assert_eq!(error, "IPC authentication failed");
        server.await.unwrap();
    }

    #[tokio::test]
    async fn authentication_rejects_a_closed_connection() {
        let (client_stream, server_stream) = duplex(4096);
        let server = tokio::spawn(async move {
            let (reader, _writer) = split(server_stream);
            let mut lines = BufReader::new(reader).lines();
            let _ = lines.next_line().await.unwrap();
        });

        let (reader, mut writer) = split(client_stream);
        let mut reader = BufReader::new(reader);
        let error = IpcClient::authenticate(&mut reader, &mut writer, "internal-secret")
            .await
            .unwrap_err();
        assert_eq!(error, "IPC authentication failed");
        server.await.unwrap();
    }
}
