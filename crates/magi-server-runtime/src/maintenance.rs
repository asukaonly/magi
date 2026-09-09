//! Durable center maintenance, independent of a connected desktop.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};

use crate::full_data_clear::{FullDataClearRuntime, PendingFullDataClear};
use magi_gateway::{
    database_gate,
    events::EventHub,
    maintenance::{MaintenanceControl, MaintenanceStatus},
};
use serde_json::Value;
use tokio::sync::Notify;

#[derive(Clone)]
pub struct Coordinator {
    marker: Arc<FullDataClearRuntime>,
    operations: PathBuf,
    restore_marker: PathBuf,
    restore_pending: Arc<Mutex<Option<PendingRestore>>>,
    connection: Arc<magi_gateway::ipc::RuntimeConnection>,
    state: Arc<Mutex<MaintenanceStatus>>,
    pending: Arc<Mutex<Option<PendingFullDataClear>>>,
    command: Arc<tokio::sync::Mutex<()>>,
    ready: Arc<AtomicBool>,
    events: Arc<EventHub>,
    security: Arc<magi_gateway::api::security::GatewaySecurity>,
    pub changed: Arc<Notify>,
}

impl Coordinator {
    pub fn open(
        root: &Path,
        initial_epoch: &str,
        ready: Arc<AtomicBool>,
        events: Arc<EventHub>,
        security: Arc<magi_gateway::api::security::GatewaySecurity>,
    ) -> Result<Self, String> {
        let marker = Arc::new(FullDataClearRuntime::new(
            root.join("runtime/full-data-clear.pending.json"),
        ));
        let operations = root.join("service/operations");
        fs::create_dir_all(&operations).map_err(|e| e.to_string())?;
        let mut state =
            read_status(&operations.join("latest.json"))?.unwrap_or(MaintenanceStatus {
                version: 2,
                operation_id: None,
                kind: None,
                phase: "idle".into(),
                data_epoch: initial_epoch.into(),
                content_epoch: initial_epoch.into(),
                result: None,
                error: None,
            });
        let mut pending = marker.read()?;
        if let Some(existing) = &pending {
            if let Some(completed) =
                read_status(&operations.join(format!("{}.json", existing.transaction_id)))?
            {
                write_status(&operations.join("latest.json"), &completed)?;
                marker.complete(&existing.transaction_id)?;
                state = completed;
                pending = None;
            } else {
                state.operation_id = Some(existing.transaction_id.clone());
                state.kind = Some("clear".into());
                state.phase = "pending".into();
                state.result = None;
                state.error = None;
                database_gate::global().close();
            }
        }
        let restore_marker = root.join("service/memory-restore.pending.json");
        let mut restore_pending = read_restore_marker(&restore_marker)?;
        if pending.is_some() && restore_pending.is_some() {
            return Err("Conflicting maintenance recovery markers".into());
        }
        if let Some(restore) = &restore_pending {
            if let Some(completed) =
                read_status(&operations.join(format!("{}.json", restore.operation_id)))?
            {
                write_status(&operations.join("latest.json"), &completed)?;
                remove_marker(&restore_marker)?;
                state = completed;
                restore_pending = None;
            } else {
                state.operation_id = Some(restore.operation_id.clone());
                state.kind = Some("restore".into());
                state.phase = "pending".into();
                state.result = None;
                state.error = None;
                database_gate::global().close();
            }
        }
        Ok(Self {
            marker,
            operations,
            restore_marker,
            restore_pending: Arc::new(Mutex::new(restore_pending)),
            connection: Arc::new(magi_gateway::ipc::RuntimeConnection::default()),
            state: Arc::new(Mutex::new(state)),
            pending: Arc::new(Mutex::new(pending)),
            command: Arc::new(tokio::sync::Mutex::new(())),
            ready,
            events,
            security,
            changed: Arc::new(Notify::new()),
        })
    }

    pub fn is_active(&self) -> bool {
        matches!(
            self.status().phase.as_str(),
            "admitting"
                | "pending"
                | "draining"
                | "clearing"
                | "restoring"
                | "verifying"
                | "failed"
        )
    }

    pub fn pending(&self) -> Option<PendingFullDataClear> {
        self.pending
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    pub fn set_phase(&self, phase: &str, error: Option<String>) {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        state.phase = phase.into();
        state.error = error;
        drop(state);
        self.events.publish(
            "state.changed",
            serde_json::json!({"resource":"maintenance"}),
        );
    }

    pub async fn complete(&self, operation_id: &str, result: Value) -> Result<(), String> {
        let _command = self.command.lock().await;
        let result = clear_receipt(&result)?;
        let completed = MaintenanceStatus {
            version: 2,
            operation_id: Some(operation_id.into()),
            kind: Some("clear".into()),
            phase: "completed".into(),
            data_epoch: operation_id.into(),
            content_epoch: operation_id.into(),
            result: Some(result),
            error: None,
        };
        let path = self.operations.join(format!("{operation_id}.json"));
        let latest = self.operations.join("latest.json");
        let saved = completed.clone();
        let marker = Arc::clone(&self.marker);
        let id = operation_id.to_owned();
        tokio::task::spawn_blocking(move || {
            write_status(&path, &saved)?;
            write_status(&latest, &saved)?;
            marker.complete(&id)
        })
        .await
        .map_err(|e| e.to_string())??;
        *self.pending.lock().unwrap_or_else(|e| e.into_inner()) = None;
        *self.state.lock().unwrap_or_else(|e| e.into_inner()) = completed;
        self.events.reset("data_cleared");
        Ok(())
    }
}

impl Coordinator {
    async fn admit_clear(&self, operation_id: String) -> Result<MaintenanceStatus, String> {
        if !(16..=128).contains(&operation_id.len())
            || !operation_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
        {
            return Err("Clear operation identifier is invalid".into());
        }
        let _command = self.command.lock().await;
        if self.pending_restore().is_some()
            || (self.is_active() && self.status().kind.as_deref() == Some("restore"))
        {
            return Err("Another maintenance operation is pending".into());
        }
        let saved_path = self.operations.join(format!("{operation_id}.json"));
        if let Some(completed) = tokio::task::spawn_blocking(move || read_status(&saved_path))
            .await
            .map_err(|e| e.to_string())??
        {
            if completed.kind.as_deref() != Some("clear") {
                return Err("Maintenance identity is already in use".into());
            }
            return Ok(self.with_current_epochs(completed));
        }
        if let Some(pending) = self.pending() {
            if pending.transaction_id != operation_id {
                return Err("Another maintenance operation is pending".into());
            }
            if self.status().phase == "failed" {
                self.set_phase("pending", None);
                self.changed.notify_one();
            }
            return Ok(self.status());
        }
        let previous = self.status();
        database_gate::global().close();
        let was_ready = self.ready.swap(false, Ordering::AcqRel);
        self.security.invalidate_resource_tickets();
        {
            let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
            state.operation_id = Some(operation_id.clone());
            state.kind = Some("clear".into());
            state.phase = "pending".into();
            state.result = None;
            state.error = None;
        }
        let marker = Arc::clone(&self.marker);
        let saved_id = operation_id.clone();
        let result = tokio::task::spawn_blocking(move || marker.begin_with_id(&saved_id))
            .await
            .map_err(|_| "Clear marker publication failed".to_owned())
            .and_then(|result| result);
        match result {
            Ok(marker) => {
                let matches = marker.transaction_id == operation_id;
                *self.pending.lock().unwrap_or_else(|e| e.into_inner()) = Some(marker.clone());
                if !matches {
                    self.state
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .operation_id = Some(marker.transaction_id);
                    self.set_phase(
                        "failed",
                        Some("Another clear recovery marker exists".into()),
                    );
                    self.changed.notify_one();
                    return Err("Another clear recovery marker exists".into());
                }
            }
            Err(error) => {
                self.set_phase("failed", Some(error.clone()));
                match self.marker.read() {
                    Ok(Some(marker)) => {
                        self.state
                            .lock()
                            .unwrap_or_else(|e| e.into_inner())
                            .operation_id = Some(marker.transaction_id.clone());
                        *self.pending.lock().unwrap_or_else(|e| e.into_inner()) = Some(marker);
                    }
                    Ok(None) => {
                        *self.state.lock().unwrap_or_else(|e| e.into_inner()) = previous;
                        database_gate::global().reopen();
                        self.ready.store(was_ready, Ordering::Release);
                    }
                    Err(_) => {}
                }
                self.changed.notify_one();
                return Err(error);
            }
        }
        self.events.reset("maintenance_started");
        self.changed.notify_one();
        Ok(self.status())
    }
}

impl MaintenanceControl for Coordinator {
    fn status(&self) -> MaintenanceStatus {
        self.state.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    fn operation_status(
        &self,
        operation_id: String,
    ) -> std::pin::Pin<
        Box<
            dyn std::future::Future<Output = Result<Option<MaintenanceStatus>, String>> + Send + '_,
        >,
    > {
        Box::pin(async move {
            validate_operation_id(&operation_id)?;
            let current = self.status();
            if current.operation_id.as_deref() == Some(&operation_id) {
                return Ok(Some(current));
            }
            let path = self.operations.join(format!("{operation_id}.json"));
            let saved = tokio::task::spawn_blocking(move || read_status(&path))
                .await
                .map_err(|e| e.to_string())??;
            Ok(saved.map(|status| self.with_current_epochs(status)))
        })
    }

    fn begin_restore(
        &self,
        operation_id: String,
    ) -> std::pin::Pin<
        Box<dyn std::future::Future<Output = Result<MaintenanceStatus, String>> + Send + '_>,
    > {
        let owner = self.clone();
        Box::pin(async move {
            tokio::spawn(async move { owner.admit_restore(operation_id).await })
                .await
                .map_err(|_| "Maintenance admission task failed".to_owned())?
        })
    }

    fn begin_clear(
        &self,
        operation_id: String,
    ) -> std::pin::Pin<
        Box<dyn std::future::Future<Output = Result<MaintenanceStatus, String>> + Send + '_>,
    > {
        let owner = self.clone();
        Box::pin(async move {
            // The admission task owns publication even if its HTTP caller disconnects.
            tokio::spawn(async move { owner.admit_clear(operation_id).await })
                .await
                .map_err(|_| "Maintenance admission task failed".to_owned())?
        })
    }
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PendingRestore {
    version: u8,
    pub operation_id: String,
    pub stage: RestoreStage,
}

#[derive(Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RestoreStage {
    Run,
    Verify,
}

impl Coordinator {
    pub fn with_connection(
        mut self,
        connection: Arc<magi_gateway::ipc::RuntimeConnection>,
    ) -> Self {
        self.connection = connection;
        self
    }

    pub fn pending_restore(&self) -> Option<PendingRestore> {
        self.restore_pending
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    pub fn has_pending(&self) -> bool {
        self.pending().is_some() || self.pending_restore().is_some()
    }

    fn with_current_epochs(&self, mut saved: MaintenanceStatus) -> MaintenanceStatus {
        let current = self.status();
        saved.data_epoch = current.data_epoch;
        saved.content_epoch = current.content_epoch;
        saved
    }

    async fn admit_restore(&self, operation_id: String) -> Result<MaintenanceStatus, String> {
        validate_restore_id(&operation_id)?;
        let _command = self.command.lock().await;
        if self.pending().is_some() {
            return Err("Another maintenance operation is pending".into());
        }
        let saved_path = self.operations.join(format!("{operation_id}.json"));
        if let Some(saved) = tokio::task::spawn_blocking(move || read_status(&saved_path))
            .await
            .map_err(|e| e.to_string())??
        {
            if saved.kind.as_deref() != Some("restore") {
                return Err("Maintenance identity is already in use".into());
            }
            return Ok(self.with_current_epochs(saved));
        }
        if let Some(pending) = self.pending_restore() {
            if pending.operation_id != operation_id {
                return Err("Another maintenance operation is pending".into());
            }
            if self.status().phase == "failed" {
                self.set_phase("pending", None);
                self.changed.notify_one();
            }
            return Ok(self.status());
        }
        if self.is_active() {
            return Err("Maintenance recovery is required".into());
        }
        let client = self
            .connection
            .current()
            .map_err(|_| "Python runtime is unavailable")?;
        let previous = self.status();
        let was_ready = self.ready.swap(false, Ordering::AcqRel);
        database_gate::global().close();
        self.security.invalidate_resource_tickets();
        {
            let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
            state.operation_id = Some(operation_id.clone());
            state.kind = Some("restore".into());
            state.phase = "admitting".into();
            state.result = None;
            state.error = None;
        }
        // Close admission before checking background jobs; the normal worker stays alive
        // until a durable marker is published, so this check cannot stop an active export.
        let preflight = async {
            let _drain = tokio::time::timeout(std::time::Duration::from_secs(30), database_gate::global().drain()).await.map_err(|_| "Requests did not drain")??;
            let response = client.request_with_timeout("api.forward", Some(serde_json::json!({
                "method":"GET", "path":"/api/memory/portability/operations/active", "query":{}, "headers":{}, "body":null
            })), std::time::Duration::from_secs(10)).await.map_err(|_| "Restore admission check failed")?;
            if response["status"] != 200 || !response.get("body").is_some_and(Value::is_null) {
                return Err("A memory data operation is active or unavailable".to_owned());
            }
            Ok::<(), String>(())
        }.await;
        if let Err(error) = preflight {
            *self.state.lock().unwrap_or_else(|e| e.into_inner()) = previous;
            database_gate::global().reopen();
            self.ready.store(
                was_ready && self.connection.current().is_ok(),
                Ordering::Release,
            );
            return Err(error);
        }
        let marker = PendingRestore {
            version: 1,
            operation_id,
            stage: RestoreStage::Run,
        };
        let path = self.restore_marker.clone();
        let saved = marker.clone();
        let published = tokio::task::spawn_blocking(move || write_status(&path, &saved))
            .await
            .map_err(|_| "Restore marker publication failed".to_owned())
            .and_then(|result| result);
        if let Err(error) = published {
            // An uncertain fsync outcome must remain closed until startup can inspect it.
            *self
                .restore_pending
                .lock()
                .unwrap_or_else(|e| e.into_inner()) = read_restore_marker(&self.restore_marker)?;
            self.set_phase("failed", Some(error.clone()));
            self.changed.notify_one();
            return Err(error);
        }
        *self
            .restore_pending
            .lock()
            .unwrap_or_else(|e| e.into_inner()) = Some(marker);
        self.set_phase("pending", None);
        self.events.reset("maintenance_started");
        self.changed.notify_one();
        Ok(self.status())
    }

    pub async fn verify_restore(&self) -> Result<(), String> {
        let _command = self.command.lock().await;
        let mut marker = self.pending_restore().ok_or("Restore owner is missing")?;
        marker.stage = RestoreStage::Verify;
        let path = self.restore_marker.clone();
        let saved = marker.clone();
        tokio::task::spawn_blocking(move || write_status(&path, &saved))
            .await
            .map_err(|e| e.to_string())??;
        *self
            .restore_pending
            .lock()
            .unwrap_or_else(|e| e.into_inner()) = Some(marker);
        self.set_phase("verifying", None);
        Ok(())
    }

    pub async fn complete_restore(&self, operation: Value) -> Result<(), String> {
        let _command = self.command.lock().await;
        let marker = self.pending_restore().ok_or("Restore owner is missing")?;
        if marker.stage != RestoreStage::Verify
            || operation["operation_id"] != marker.operation_id
            || operation["kind"] != "restore"
            || !matches!(operation["status"].as_str(), Some("succeeded" | "failed"))
        {
            return Err("Restore completion is not verified".into());
        }
        let completed = MaintenanceStatus {
            version: 2,
            operation_id: Some(marker.operation_id.clone()),
            kind: Some("restore".into()),
            phase: "completed".into(),
            data_epoch: marker.operation_id.clone(),
            content_epoch: self.status().content_epoch,
            result: Some(
                serde_json::json!({"success":operation["status"] == "succeeded", "rollback_performed":operation["rollback_performed"] == true}),
            ),
            error: None,
        };
        let saved = completed.clone();
        let path = self
            .operations
            .join(format!("{}.json", marker.operation_id));
        let latest = self.operations.join("latest.json");
        let marker_path = self.restore_marker.clone();
        tokio::task::spawn_blocking(move || {
            write_status(&path, &saved)?;
            write_status(&latest, &saved)?;
            remove_marker(&marker_path)
        })
        .await
        .map_err(|e| e.to_string())??;
        *self
            .restore_pending
            .lock()
            .unwrap_or_else(|e| e.into_inner()) = None;
        *self.state.lock().unwrap_or_else(|e| e.into_inner()) = completed;
        self.events.reset("memory_restored");
        Ok(())
    }
}

fn validate_operation_id(id: &str) -> Result<(), String> {
    if !(16..=128).contains(&id.len())
        || !id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
    {
        return Err("Maintenance operation identifier is invalid".into());
    }
    Ok(())
}

fn validate_restore_id(id: &str) -> Result<(), String> {
    let parsed = uuid::Uuid::parse_str(id).map_err(|_| "Restore identity is invalid")?;
    if parsed.get_version_num() != 4 || parsed.to_string() != id {
        return Err("Restore identity is invalid".into());
    }
    Ok(())
}

fn read_restore_marker(path: &Path) -> Result<Option<PendingRestore>, String> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 4096 {
        return Err("Restore marker is invalid".into());
    }
    let marker: PendingRestore =
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|_| "Restore marker is invalid")?;
    if marker.version != 1 {
        return Err("Restore marker version is invalid".into());
    }
    validate_restore_id(&marker.operation_id)?;
    Ok(Some(marker))
}

fn remove_marker(path: &Path) -> Result<(), String> {
    fs::remove_file(path).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    fs::File::open(path.parent().ok_or("Maintenance directory is missing")?)
        .and_then(|file| file.sync_all())
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Persist counts only; completion records survive deletion of private user content.
fn clear_receipt(response: &Value) -> Result<Value, String> {
    if response["success"] != true
        || response["warnings"]
            .as_array()
            .is_none_or(|items| !items.is_empty())
    {
        return Err("Full clear has not completed successfully".into());
    }
    let mut results = serde_json::Map::new();
    for area in ["l0", "l1", "l2", "l3", "l4", "chat_context"] {
        let result = &response["results"][area];
        let count = result["count"]
            .as_u64()
            .ok_or("Clear result count is invalid")?;
        if result["cleared"] != true {
            return Err("Full clear has an incomplete area".into());
        }
        results.insert(
            area.into(),
            serde_json::json!({"cleared":true,"count":count}),
        );
    }
    Ok(serde_json::json!({"success":true,"results":results,"warnings":[]}))
}

fn read_status(path: &Path) -> Result<Option<MaintenanceStatus>, String> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 65536 {
        return Err("Maintenance record is invalid".into());
    }
    let status: MaintenanceStatus =
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|_| "Maintenance record is invalid")?;
    if status.version != 2
        || status.phase != "completed"
        || status.operation_id.is_none()
        || !matches!(status.kind.as_deref(), Some("clear" | "restore"))
        || status.content_epoch.is_empty()
        || status.data_epoch.is_empty()
    {
        return Err("Maintenance completion record is invalid".into());
    }
    if path.file_stem().and_then(|name| name.to_str()) != Some("latest")
        && path.file_stem().and_then(|name| name.to_str()) != status.operation_id.as_deref()
    {
        return Err("Maintenance record identity is invalid".into());
    }
    Ok(Some(status))
}

fn write_status(path: &Path, status: &impl serde::Serialize) -> Result<(), String> {
    let temporary = path.with_extension("tmp");
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
    let bytes = serde_json::to_vec(status).map_err(|e| e.to_string())?;
    if bytes.len() > 65536 {
        return Err("Maintenance result exceeds the size limit".into());
    }
    file.write_all(&bytes).map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    drop(file);
    fs::rename(&temporary, path).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    fs::File::open(path.parent().ok_or("Maintenance directory is missing")?)
        .and_then(|file| file.sync_all())
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cleared_response() -> Value {
        let results: serde_json::Map<String, Value> =
            ["l0", "l1", "l2", "l3", "l4", "chat_context"]
                .into_iter()
                .map(|area| (area.into(), serde_json::json!({"cleared":true,"count":0})))
                .collect();
        serde_json::json!({"success":true,"results":results,"warnings":[]})
    }

    #[tokio::test]
    async fn restore_recovery_preserves_content_epoch_and_historical_receipts_use_current_epochs() {
        let root =
            std::env::temp_dir().join(format!("magi-restore-maintenance-{}", uuid::Uuid::new_v4()));
        let security = Arc::new(magi_gateway::api::security::GatewaySecurity::new("owner"));
        let open = || {
            Coordinator::open(
                &root,
                "original",
                Arc::new(AtomicBool::new(false)),
                Arc::new(EventHub::new("center".into())),
                Arc::clone(&security),
            )
            .unwrap()
        };
        let coordinator = open();
        let clear_id = "earlier-clear-operation";
        coordinator.begin_clear(clear_id.into()).await.unwrap();
        coordinator
            .complete(clear_id, cleared_response())
            .await
            .unwrap();
        let restore_id = uuid::Uuid::new_v4().to_string();
        let marker = PendingRestore {
            version: 1,
            operation_id: restore_id.clone(),
            stage: RestoreStage::Run,
        };
        write_status(&coordinator.restore_marker, &marker).unwrap();
        drop(coordinator);
        let coordinator = open();
        assert_eq!(coordinator.status().kind.as_deref(), Some("restore"));
        assert_eq!(coordinator.status().content_epoch, clear_id);
        assert!(coordinator
            .begin_clear("different-clear-operation".into())
            .await
            .is_err());
        let operation = serde_json::json!({"operation_id":restore_id,"kind":"restore","status":"succeeded","private_path":"private"});
        assert!(coordinator
            .complete_restore(operation.clone())
            .await
            .is_err());
        coordinator.verify_restore().await.unwrap();
        drop(coordinator);
        let coordinator = open();
        assert!(matches!(
            coordinator.pending_restore().unwrap().stage,
            RestoreStage::Verify
        ));
        coordinator.complete_restore(operation).await.unwrap();
        let old = coordinator
            .operation_status(clear_id.into())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(old.operation_id.as_deref(), Some(clear_id));
        assert_eq!(old.data_epoch, restore_id);
        assert_eq!(old.content_epoch, clear_id);
        assert_eq!(
            coordinator
                .begin_clear(clear_id.into())
                .await
                .unwrap()
                .data_epoch,
            restore_id
        );
        assert!(coordinator
            .status()
            .result
            .unwrap()
            .get("private_path")
            .is_none());
        assert!(!coordinator.has_pending());
        // Reproduce interruption after durable completion and before marker unlink.
        write_status(&coordinator.restore_marker, &marker).unwrap();
        drop(coordinator);
        let coordinator = open();
        assert!(!coordinator.has_pending());
        assert_eq!(coordinator.status().data_epoch, restore_id);
        assert_eq!(
            coordinator
                .begin_restore(restore_id.clone())
                .await
                .unwrap()
                .phase,
            "completed"
        );
        assert!(coordinator
            .operation_status("../../private".into())
            .await
            .is_err());
        database_gate::global().reopen();
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn receipt_excludes_private_fields_and_rejects_partial_clear() {
        let mut response = cleared_response();
        response["private_detail"] = serde_json::json!("private content");
        assert!(clear_receipt(&response)
            .unwrap()
            .get("private_detail")
            .is_none());
        response["results"]["l0"]["cleared"] = serde_json::json!(false);
        assert!(clear_receipt(&response).is_err());
    }

    #[tokio::test]
    async fn admission_survives_cancellation_of_the_requesting_client() {
        let root = std::env::temp_dir().join(format!(
            "magi-admission-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let security = Arc::new(magi_gateway::api::security::GatewaySecurity::new("owner"));
        let coordinator = Coordinator::open(
            &root,
            "initial",
            Arc::new(AtomicBool::new(true)),
            Arc::new(EventHub::new("server".into())),
            security,
        )
        .unwrap();
        let lock = coordinator.command.lock().await;
        let request_owner = coordinator.clone();
        let request = tokio::spawn(async move {
            request_owner
                .begin_clear("cancelled-client-operation".into())
                .await
        });
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while Arc::strong_count(&coordinator.command) < 3 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        request.abort();
        let _ = request.await;
        drop(lock);
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while coordinator.pending().is_none() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(
            coordinator.pending().unwrap().transaction_id,
            "cancelled-client-operation"
        );
        assert_eq!(
            coordinator.marker.read().unwrap().unwrap().transaction_id,
            "cancelled-client-operation"
        );
        coordinator
            .complete("cancelled-client-operation", cleared_response())
            .await
            .unwrap();
        database_gate::global().reopen();
        fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn pending_and_completed_clear_records_recover_without_changing_identity() {
        let id = "clear-durable-recovery-test";
        let root = std::env::temp_dir().join(format!("magi-maintenance-{}", std::process::id()));
        let security = Arc::new(magi_gateway::api::security::GatewaySecurity::new("owner"));
        let ready = Arc::new(AtomicBool::new(true));
        let events = Arc::new(EventHub::new("server".into()));
        let open = || {
            Coordinator::open(
                &root,
                "original-epoch",
                Arc::clone(&ready),
                Arc::clone(&events),
                Arc::clone(&security),
            )
            .unwrap()
        };
        let coordinator = open();
        assert_eq!(
            coordinator.begin_clear(id.into()).await.unwrap().phase,
            "pending"
        );
        assert!(!ready.load(Ordering::Acquire));
        assert!(coordinator
            .begin_clear("clear-different-operation".into())
            .await
            .is_err());
        drop(coordinator);
        let coordinator = open();
        assert_eq!(coordinator.pending().unwrap().transaction_id, id);
        assert_eq!(coordinator.status().data_epoch, "original-epoch");
        coordinator.complete(id, cleared_response()).await.unwrap();
        assert_eq!(
            coordinator.begin_clear(id.into()).await.unwrap().phase,
            "completed"
        );
        drop(coordinator);
        // Reproduce a crash after the completion record was synced but before marker removal.
        let marker = FullDataClearRuntime::new(root.join("runtime/full-data-clear.pending.json"));
        marker.begin_with_id(id).unwrap();
        let coordinator = open();
        assert!(coordinator.pending().is_none());
        assert!(marker.read().unwrap().is_none());
        assert_eq!(coordinator.status().data_epoch, id);
        assert_eq!(
            coordinator.begin_clear(id.into()).await.unwrap().phase,
            "completed"
        );
        database_gate::global().reopen();
        fs::remove_dir_all(root).unwrap();
    }
}
