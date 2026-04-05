//! IPC client for communicating with the Python worker over NDJSON.
//!
//! The client maintains a single persistent connection. Requests are multiplexed
//! by UUID. Stream and event messages are dispatched to registered receivers.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::sync::{mpsc, oneshot, Mutex};

use super::protocol::{self, InboundMessage, IpcError, IpcNotify, IpcRequest};

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

/// IPC client connected to the Python worker.
#[derive(Clone)]
pub struct IpcClient {
    /// Serialised write access to the socket.
    write_tx: mpsc::Sender<String>,
    /// In-flight request map (shared with the read loop).
    pending: Arc<Mutex<PendingMap>>,
    /// Channel for unsolicited events pushed by Python.
    event_tx: mpsc::Sender<(String, Value)>,
}

impl IpcClient {
    /// Connect to the IPC socket at `path` (Unix) and spawn the read/write loops.
    /// Returns the client handle and an event receiver for unsolicited events.
    #[cfg(unix)]
    pub async fn connect(
        path: &str,
    ) -> Result<(Self, mpsc::Receiver<(String, Value)>), String> {
        let stream = tokio::net::UnixStream::connect(path)
            .await
            .map_err(|e| format!("IPC connect failed: {e}"))?;
        let (reader, writer) = stream.into_split();
        Self::start(BufReader::new(reader), writer)
    }

    /// Connect to the IPC socket via TCP loopback (Windows fallback).
    #[cfg(not(unix))]
    pub async fn connect(
        addr: &str,
    ) -> Result<(Self, mpsc::Receiver<(String, Value)>), String> {
        let stream = tokio::net::TcpStream::connect(addr)
            .await
            .map_err(|e| format!("IPC connect failed: {e}"))?;
        let (reader, writer) = stream.into_split();
        Self::start(BufReader::new(reader), writer)
    }

    fn start<R, W>(reader: BufReader<R>, writer: W) -> Result<(Self, mpsc::Receiver<(String, Value)>), String>
    where
        R: tokio::io::AsyncRead + Unpin + Send + 'static,
        W: tokio::io::AsyncWrite + Unpin + Send + 'static,
    {
        let pending: Arc<Mutex<PendingMap>> = Arc::new(Mutex::new(HashMap::new()));
        let (write_tx, write_rx) = mpsc::channel::<String>(256);
        let (event_tx, event_rx) = mpsc::channel::<(String, Value)>(256);

        // Spawn write loop
        tokio::spawn(Self::write_loop(writer, write_rx));

        // Spawn read loop
        let read_pending = Arc::clone(&pending);
        let read_event_tx = event_tx.clone();
        tokio::spawn(Self::read_loop(reader, read_pending, read_event_tx));

        Ok((
            Self {
                write_tx,
                pending,
                event_tx,
            },
            event_rx,
        ))
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

    /// Send a request and wait for the response.
    pub async fn request(
        &self,
        method: &str,
        params: Option<Value>,
    ) -> Result<Value, IpcError> {
        let id = uuid::Uuid::new_v4().to_string();
        let (tx, rx) = oneshot::channel();

        {
            let mut map = self.pending.lock().await;
            map.insert(id.clone(), PendingRequest { tx });
        }

        let msg = IpcRequest {
            id: id.clone(),
            method: method.to_string(),
            params,
        };
        let mut line = serde_json::to_string(&msg).unwrap();
        line.push('\n');

        if self.write_tx.send(line).await.is_err() {
            let mut map = self.pending.lock().await;
            map.remove(&id);
            return Err(IpcError {
                code: -2,
                message: "IPC write channel closed".to_string(),
            });
        }

        match rx.await {
            Ok(ResponseEnvelope::Result(v)) => Ok(v),
            Ok(ResponseEnvelope::Error(e)) => Err(e),
            Err(_) => Err(IpcError {
                code: -3,
                message: "Request dropped (connection closed)".to_string(),
            }),
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
                    let mut map = pending.lock().await;
                    if let Some(req) = map.remove(&id) {
                        let _ = req.tx.send(ResponseEnvelope::Result(result));
                    }
                }
                InboundMessage::Error { id, error } => {
                    let mut map = pending.lock().await;
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

        // Connection closed — fail all pending requests
        let mut map = pending.lock().await;
        for (_, req) in map.drain() {
            let _ = req.tx.send(ResponseEnvelope::Error(IpcError {
                code: -4,
                message: "IPC connection closed".to_string(),
            }));
        }
    }
}
