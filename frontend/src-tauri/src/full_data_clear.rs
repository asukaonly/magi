use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

const MARKER_VERSION: u8 = 1;
const MAX_MARKER_BYTES: u64 = 1024;
const TEMP_MARKER_PREFIX: &str = ".full-data-clear-";
const TEMP_MARKER_SUFFIX: &str = ".tmp";
static TRANSACTION_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PendingFullDataClear {
    version: u8,
    pub transaction_id: String,
}

pub struct FullDataClearRuntime {
    marker_path: PathBuf,
    gate: Mutex<()>,
}

impl FullDataClearRuntime {
    pub fn new(marker_path: PathBuf) -> Self {
        Self {
            marker_path,
            gate: Mutex::new(()),
        }
    }

    pub fn begin(&self) -> Result<PendingFullDataClear, String> {
        let _guard = lock_unpoisoned(&self.gate);
        if let Some(existing) = read_marker(&self.marker_path)? {
            return Ok(existing);
        }

        let marker = PendingFullDataClear {
            version: MARKER_VERSION,
            transaction_id: new_transaction_id(),
        };
        write_marker_atomically(&self.marker_path, &marker)?;
        Ok(marker)
    }

    pub fn read(&self) -> Result<Option<PendingFullDataClear>, String> {
        let _guard = lock_unpoisoned(&self.gate);
        read_marker(&self.marker_path)
    }

    pub fn complete(&self, transaction_id: &str) -> Result<(), String> {
        let _guard = lock_unpoisoned(&self.gate);
        let Some(marker) = read_marker(&self.marker_path)? else {
            return Err("No full data clear transaction is pending".to_string());
        };
        if marker.transaction_id != transaction_id {
            return Err(
                "Full data clear transaction does not match the pending marker".to_string(),
            );
        }

        let temp_path = marker_temp_path(&self.marker_path, transaction_id)?;
        remove_file_if_present(&temp_path, "full data clear temporary marker")?;
        fs::remove_file(&self.marker_path)
            .map_err(|error| format!("Failed to remove full data clear marker: {error}"))?;
        sync_parent_directory(&self.marker_path)?;
        Ok(())
    }
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

fn new_transaction_id() -> String {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let counter = TRANSACTION_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!(
        "clear-{:016x}{:08x}{:08x}{:016x}",
        duration.as_secs(),
        duration.subsec_nanos(),
        std::process::id(),
        counter,
    )
}

fn read_marker(path: &Path) -> Result<Option<PendingFullDataClear>, String> {
    let temporary_paths = temporary_marker_paths(path)?;
    if temporary_paths.len() > 1 {
        return Err("Multiple full data clear temporary markers exist".to_string());
    }

    let Some(temp_path) = temporary_paths.first() else {
        return read_marker_file(path, "full data clear marker");
    };
    let temporary = recover_marker_from_temp_name(temp_path)?;

    match read_marker_file(path, "full data clear marker") {
        Ok(Some(published)) => {
            if temporary != published {
                return Err(
                    "Full data clear marker conflicts with its temporary marker".to_string()
                );
            }
        }
        Ok(None) => publish_recovered_marker(path, &temporary)?,
        Err(_) => {
            remove_file_if_present(path, "invalid full data clear marker")?;
            publish_recovered_marker(path, &temporary)?;
        }
    }
    remove_file_if_present(temp_path, "full data clear temporary marker")?;
    sync_parent_directory(path)?;
    Ok(Some(temporary))
}

fn recover_marker_from_temp_name(path: &Path) -> Result<PendingFullDataClear, String> {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "Full data clear temporary marker name is invalid".to_string())?;
    let transaction_id = name
        .strip_prefix(TEMP_MARKER_PREFIX)
        .and_then(|value| value.strip_suffix(TEMP_MARKER_SUFFIX))
        .filter(|value| is_valid_transaction_id(value))
        .ok_or_else(|| "Full data clear temporary marker name is invalid".to_string())?;
    let recovered = PendingFullDataClear {
        version: MARKER_VERSION,
        transaction_id: transaction_id.to_string(),
    };

    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Failed to inspect full data clear temporary marker: {error}"))?;
    if !metadata.file_type().is_file() || metadata.len() > MAX_MARKER_BYTES {
        return Err("Full data clear temporary marker is not a valid marker file".to_string());
    }
    let bytes = fs::read(path)
        .map_err(|error| format!("Failed to read full data clear temporary marker: {error}"))?;
    if let Ok(decoded) = serde_json::from_slice::<PendingFullDataClear>(&bytes) {
        if decoded.version != MARKER_VERSION
            || !is_valid_transaction_id(&decoded.transaction_id)
            || decoded != recovered
        {
            return Err("Full data clear marker conflicts with its temporary marker".to_string());
        }
    }
    Ok(recovered)
}

fn publish_recovered_marker(path: &Path, marker: &PendingFullDataClear) -> Result<(), String> {
    let payload = serde_json::to_vec(marker)
        .map_err(|error| format!("Failed to encode recovered full data clear marker: {error}"))?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("Failed to publish recovered full data clear marker: {error}"))?;
    file.write_all(&payload)
        .map_err(|error| format!("Failed to write recovered full data clear marker: {error}"))?;
    file.sync_all()
        .map_err(|error| format!("Failed to sync recovered full data clear marker: {error}"))?;
    drop(file);
    sync_parent_directory(path)?;
    Ok(())
}

fn read_marker_file(path: &Path, label: &str) -> Result<Option<PendingFullDataClear>, String> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("Failed to inspect {label}: {error}")),
    };
    if !metadata.file_type().is_file() || metadata.len() > MAX_MARKER_BYTES {
        return Err(format!("{label} is not a valid marker file"));
    }
    let bytes = fs::read(path).map_err(|error| format!("Failed to read {label}: {error}"))?;
    let marker: PendingFullDataClear =
        serde_json::from_slice(&bytes).map_err(|error| format!("{label} is invalid: {error}"))?;
    if marker.version != MARKER_VERSION || !is_valid_transaction_id(&marker.transaction_id) {
        return Err(format!("{label} has invalid fields"));
    }
    Ok(Some(marker))
}

fn temporary_marker_paths(marker_path: &Path) -> Result<Vec<PathBuf>, String> {
    let Some(parent) = marker_path.parent() else {
        return Err("Full data clear marker has no parent directory".to_string());
    };
    let entries = match fs::read_dir(parent) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => {
            return Err(format!(
                "Failed to inspect full data clear marker directory: {error}"
            ));
        }
    };
    let mut paths = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|error| {
            format!("Failed to inspect full data clear temporary marker: {error}")
        })?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.starts_with(TEMP_MARKER_PREFIX) && name.ends_with(TEMP_MARKER_SUFFIX) {
            paths.push(entry.path());
        }
    }
    paths.sort();
    Ok(paths)
}

fn marker_temp_path(path: &Path, transaction_id: &str) -> Result<PathBuf, String> {
    let parent = path
        .parent()
        .ok_or_else(|| "Full data clear marker has no parent directory".to_string())?;
    Ok(parent.join(format!(
        "{TEMP_MARKER_PREFIX}{transaction_id}{TEMP_MARKER_SUFFIX}"
    )))
}

fn remove_file_if_present(path: &Path, label: &str) -> Result<(), String> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!("Failed to remove {label}: {error}")),
    }
}

fn is_valid_transaction_id(value: &str) -> bool {
    (16..=128).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

fn write_marker_atomically(path: &Path, marker: &PendingFullDataClear) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "Full data clear marker has no parent directory".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("Failed to create full data clear marker directory: {error}"))?;

    let temp_path = marker_temp_path(path, &marker.transaction_id)?;
    let payload = serde_json::to_vec(marker)
        .map_err(|error| format!("Failed to encode full data clear marker: {error}"))?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp_path)
        .map_err(|error| format!("Failed to create full data clear marker: {error}"))?;

    let write_result = (|| -> Result<(), String> {
        file.write_all(&payload)
            .map_err(|error| format!("Failed to write full data clear marker: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("Failed to sync full data clear marker: {error}"))?;
        drop(file);
        fs::rename(&temp_path, path)
            .map_err(|error| format!("Failed to publish full data clear marker: {error}"))?;
        sync_parent_directory(path)
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&temp_path);
    }
    write_result
}

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "Full data clear marker has no parent directory".to_string())?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| format!("Failed to sync full data clear marker directory: {error}"))
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{marker_temp_path, FullDataClearRuntime, PendingFullDataClear, MARKER_VERSION};
    use std::fs::{self, OpenOptions};
    use std::io::Write;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

    fn test_marker_path(name: &str) -> PathBuf {
        let id = TEST_COUNTER.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir()
            .join(format!(
                "magi-full-data-clear-{name}-{}-{id}",
                std::process::id()
            ))
            .join("runtime")
            .join("full-data-clear.pending.json")
    }

    fn write_crashed_temp(marker_path: &PathBuf, marker: &PendingFullDataClear) -> PathBuf {
        fs::create_dir_all(marker_path.parent().unwrap()).unwrap();
        let temp_path = marker_temp_path(marker_path, &marker.transaction_id).unwrap();
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temp_path)
            .unwrap();
        file.write_all(&serde_json::to_vec(marker).unwrap())
            .unwrap();
        file.sync_all().unwrap();
        temp_path
    }

    #[test]
    fn pending_marker_survives_runtime_restart_and_is_reused() {
        let marker_path = test_marker_path("restart");
        let first = FullDataClearRuntime::new(marker_path.clone())
            .begin()
            .unwrap();

        let reopened = FullDataClearRuntime::new(marker_path.clone());
        assert_eq!(reopened.read().unwrap(), Some(first.clone()));
        assert_eq!(reopened.begin().unwrap(), first);

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn completion_requires_the_pending_transaction_and_removes_the_marker() {
        let marker_path = test_marker_path("complete");
        let runtime = FullDataClearRuntime::new(marker_path.clone());
        let marker = runtime.begin().unwrap();

        assert!(runtime.complete("clear-wrong-transaction").is_err());
        assert_eq!(runtime.read().unwrap(), Some(marker.clone()));
        let duplicate_temp = write_crashed_temp(&marker_path, &marker);
        runtime.complete(&marker.transaction_id).unwrap();
        assert_eq!(runtime.read().unwrap(), None);
        assert!(!duplicate_temp.exists());
        assert!(runtime.complete(&marker.transaction_id).is_err());

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn synced_temp_is_recovered_after_crash_before_publish() {
        let marker_path = test_marker_path("temp-recovery");
        let marker = PendingFullDataClear {
            version: MARKER_VERSION,
            transaction_id: "clear-temp-recovery-transaction".to_string(),
        };
        let temp_path = write_crashed_temp(&marker_path, &marker);

        let runtime = FullDataClearRuntime::new(marker_path.clone());
        assert_eq!(runtime.read().unwrap(), Some(marker.clone()));
        assert_eq!(
            fs::read(&marker_path).unwrap(),
            serde_json::to_vec(&marker).unwrap()
        );
        assert!(!temp_path.exists());

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn partial_temp_is_recovered_from_its_valid_transaction_name() {
        let marker_path = test_marker_path("partial-temp");
        fs::create_dir_all(marker_path.parent().unwrap()).unwrap();
        let transaction_id = "clear-partial-temp-transaction";
        let temp_path = marker_path
            .parent()
            .unwrap()
            .join(format!(".full-data-clear-{transaction_id}.tmp"));
        fs::write(&temp_path, b"{\"version\":").unwrap();

        let recovered = FullDataClearRuntime::new(marker_path.clone())
            .read()
            .unwrap()
            .unwrap();

        assert_eq!(recovered.transaction_id, transaction_id);
        assert_eq!(recovered.version, MARKER_VERSION);
        assert!(!temp_path.exists());
        assert!(marker_path.exists());

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn invalid_temp_name_blocks_normal_startup() {
        let marker_path = test_marker_path("invalid-temp-name");
        fs::create_dir_all(marker_path.parent().unwrap()).unwrap();
        let invalid_temp = marker_path
            .parent()
            .unwrap()
            .join(".full-data-clear-short.tmp");
        fs::write(&invalid_temp, b"").unwrap();

        assert!(FullDataClearRuntime::new(marker_path.clone())
            .read()
            .is_err());
        assert!(!marker_path.exists());

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn multiple_temps_block_normal_startup() {
        let marker_path = test_marker_path("multiple-temp");
        for transaction_id in ["clear-temp-transaction-one", "clear-temp-transaction-two"] {
            write_crashed_temp(
                &marker_path,
                &PendingFullDataClear {
                    version: MARKER_VERSION,
                    transaction_id: transaction_id.to_string(),
                },
            );
        }
        assert!(FullDataClearRuntime::new(marker_path.clone())
            .read()
            .is_err());
        assert!(!marker_path.exists());

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn valid_temp_payload_conflicting_with_its_name_blocks_startup() {
        let marker_path = test_marker_path("conflicting-temp");
        fs::create_dir_all(marker_path.parent().unwrap()).unwrap();
        let temp_path = marker_path
            .parent()
            .unwrap()
            .join(".full-data-clear-clear-name-transaction.tmp");
        let conflicting = PendingFullDataClear {
            version: MARKER_VERSION,
            transaction_id: "clear-payload-transaction".to_string(),
        };
        fs::write(&temp_path, serde_json::to_vec(&conflicting).unwrap()).unwrap();

        assert!(FullDataClearRuntime::new(marker_path.clone())
            .read()
            .is_err());
        assert!(!marker_path.exists());

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn invalid_marker_blocks_recovery_instead_of_being_discarded() {
        let marker_path = test_marker_path("invalid");
        fs::create_dir_all(marker_path.parent().unwrap()).unwrap();
        fs::write(&marker_path, b"not-json").unwrap();

        let runtime = FullDataClearRuntime::new(marker_path.clone());
        assert!(runtime.read().is_err());
        assert!(runtime.begin().is_err());

        let _ = fs::remove_dir_all(marker_path.parent().unwrap().parent().unwrap());
    }
}
