#![cfg(unix)]

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::{body::Body, http::Request};
use magi_gateway::{api, database_gate, ipc};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::sync::{mpsc, oneshot};
use tower::ServiceExt;

static GATE_TEST_LOCK: Mutex<()> = Mutex::new(());
const TOKEN: &str = "request-cancellation-test-token";

struct Worker {
    client: Arc<ipc::IpcClient>,
    incoming: mpsc::UnboundedReceiver<Value>,
    response: Option<oneshot::Sender<Value>>,
    task: tokio::task::JoinHandle<()>,
    socket: PathBuf,
}

impl Worker {
    async fn start() -> Self {
        let socket =
            std::env::temp_dir().join(format!("magi-cancel-{}.sock", uuid::Uuid::new_v4()));
        let listener = tokio::net::UnixListener::bind(&socket).unwrap();
        let (incoming_tx, incoming) = mpsc::unbounded_channel();
        let (response, mut response_rx) = oneshot::channel::<Value>();
        let task = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let (reader, mut writer) = stream.into_split();
            let mut lines = BufReader::new(reader).lines();
            let auth: Value =
                serde_json::from_str(&lines.next_line().await.unwrap().unwrap()).unwrap();
            writer
                .write_all(
                    format!(
                        "{}\n",
                        json!({"id":auth["id"], "result":{"authenticated":true}})
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
            loop {
                tokio::select! {
                    line = lines.next_line() => {
                        let Some(line) = line.unwrap() else { break; };
                        incoming_tx.send(serde_json::from_str(&line).unwrap()).unwrap();
                    }
                    response = &mut response_rx => {
                        if let Ok(response) = response {
                            writer.write_all(format!("{response}\n").as_bytes()).await.unwrap();
                        }
                        break;
                    }
                }
            }
        });
        let (client, _events) = ipc::IpcClient::connect(socket.to_str().unwrap(), TOKEN)
            .await
            .unwrap();
        Self {
            client: Arc::new(client),
            incoming,
            response: Some(response),
            task,
            socket,
        }
    }

    fn router(&self) -> axum::Router {
        api::build_router(api::state::ApiState::new(
            Arc::clone(&self.client),
            Arc::new(api::security::GatewaySecurity::new(TOKEN)),
        ))
    }

    async fn next_request(&mut self) -> Value {
        tokio::time::timeout(Duration::from_secs(1), self.incoming.recv())
            .await
            .unwrap()
            .unwrap()
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        self.client.disconnect();
        self.task.abort();
        let _ = std::fs::remove_file(&self.socket);
        database_gate::global().reopen();
    }
}

#[tokio::test]
async fn dropping_public_proxy_read_cancels_its_ipc_work_and_releases_admission() {
    let _serial = GATE_TEST_LOCK.lock().unwrap();
    let mut worker = Worker::start().await;
    let call = tokio::spawn(
        worker.router().oneshot(
            Request::builder()
                .uri("/api/audit/slow-read")
                .header("x-magi-session-token", TOKEN)
                .body(Body::empty())
                .unwrap(),
        ),
    );
    let request = worker.next_request().await;
    assert_eq!(request["params"]["method"], "GET");
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
    let cancel = worker.next_request().await;
    assert_eq!(cancel["method"], "ipc.cancel");
    assert_eq!(cancel["params"]["id"], request["id"]);
    let permit = tokio::time::timeout(Duration::from_secs(1), database_gate::global().drain())
        .await
        .unwrap()
        .unwrap();
    drop(permit);
}

#[tokio::test]
async fn dropping_public_proxy_write_keeps_work_and_admission_until_response() {
    let _serial = GATE_TEST_LOCK.lock().unwrap();
    let mut worker = Worker::start().await;
    let call = tokio::spawn(
        worker.router().oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/audit/slow-write")
                .header("x-magi-session-token", TOKEN)
                .body(Body::empty())
                .unwrap(),
        ),
    );
    let request = worker.next_request().await;
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
    assert!(
        tokio::time::timeout(Duration::from_millis(50), worker.incoming.recv())
            .await
            .is_err()
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(50), database_gate::global().drain())
            .await
            .is_err()
    );
    worker
        .response
        .take()
        .unwrap()
        .send(json!({
            "id":request["id"], "result":{"status":200,"body":{"success":true}}
        }))
        .unwrap();
    let permit = tokio::time::timeout(Duration::from_secs(1), database_gate::global().drain())
        .await
        .unwrap()
        .unwrap();
    drop(permit);
}

#[tokio::test]
async fn dropping_native_request_preserves_admission_until_handler_finishes() {
    let _serial = GATE_TEST_LOCK.lock().unwrap();
    let worker = Worker::start().await;
    let (started_tx, started_rx) = oneshot::channel();
    let (finish_tx, finish_rx) = oneshot::channel();
    let body = Body::from_stream(futures_util::stream::once(async move {
        started_tx.send(()).unwrap();
        finish_rx.await.unwrap();
        Ok::<_, std::io::Error>(axum::body::Bytes::from_static(b"{}"))
    }));
    // Missing required fields ensure validation finishes without touching a domain database.
    let call = tokio::spawn(
        worker.router().oneshot(
            Request::builder()
                .method("PATCH")
                .uri("/api/messages/session/audit")
                .header("x-magi-session-token", TOKEN)
                .header("content-type", "application/json")
                .body(body)
                .unwrap(),
        ),
    );
    tokio::time::timeout(Duration::from_secs(1), started_rx)
        .await
        .unwrap()
        .unwrap();
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
    assert!(
        tokio::time::timeout(Duration::from_millis(50), database_gate::global().drain())
            .await
            .is_err()
    );
    finish_tx.send(()).unwrap();
    let permit = tokio::time::timeout(Duration::from_secs(1), database_gate::global().drain())
        .await
        .unwrap()
        .unwrap();
    drop(permit);
}
