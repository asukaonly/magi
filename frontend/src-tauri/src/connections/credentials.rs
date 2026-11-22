//! Device credentials stored in the OS keychain and referenced from private desktop metadata.

use std::collections::BTreeMap;
#[cfg(any(unix, test))]
use std::fs;
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use magi_platform::credentials::{
    is_secret_ref, make_secret_ref, scope_service_name, OsSecretBackend,
};
use serde::{Deserialize, Serialize};

const INVALID: &str = "local_credentials_invalid";
const MISSING: &str = "local_credential_missing";
const LIMIT: u64 = 65_536;
const SERVICE_BASE: &str = "com.magi.desktop.connections";
const SECRET_NAMESPACE: &str = "desktop_connection";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CredentialFile {
    version: u8,
    credentials: BTreeMap<String, String>,
}

#[cfg(test)]
fn default_backend_for_dir(directory: &Path) -> Arc<dyn OsSecretBackend> {
    use std::sync::{Mutex, OnceLock};

    static TEST_BACKENDS: OnceLock<Mutex<BTreeMap<PathBuf, Arc<magi_platform::credentials::InMemorySecretBackend>>>> =
        OnceLock::new();
    let registry = TEST_BACKENDS.get_or_init(|| Mutex::new(BTreeMap::new()));
    let mut guard = registry.lock().expect("test backend registry poisoned");
    let key = directory.to_path_buf();
    let backend = guard
        .entry(key)
        .or_insert_with(|| Arc::new(magi_platform::credentials::InMemorySecretBackend::new()));
    backend.clone()
}

#[cfg(not(test))]
fn default_backend_for_dir(_directory: &Path) -> Arc<dyn OsSecretBackend> {
    Arc::new(magi_platform::credentials::NativeSecretBackend::new())
}

#[derive(Clone)]
pub struct CredentialStore {
    directory: PathBuf,
    service: String,
    backend: Arc<dyn OsSecretBackend>,
}

impl CredentialStore {
    pub fn new(directory: &Path) -> Self {
        Self::with_backend(directory, default_backend_for_dir(directory))
    }

    pub fn with_backend(directory: &Path, backend: Arc<dyn OsSecretBackend>) -> Self {
        let dir_buf: PathBuf = directory.into();
        let service = scope_service_name(SERVICE_BASE, &dir_buf.to_string_lossy());
        Self {
            directory: dir_buf,
            service,
            backend,
        }
    }

    fn path(&self) -> PathBuf {
        self.directory.join("credentials.json")
    }

    fn read_raw(&self) -> Result<CredentialFile, String> {
        magi_platform::private_data::protect_magi_data_root(&self.directory)?;
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_NOFOLLOW);
        }
        let file = match options.open(self.path()) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(CredentialFile {
                    version: 1,
                    credentials: BTreeMap::new(),
                });
            }
            Err(_) => return Err("Could not read local connection credentials".into()),
        };
        if !file.metadata().map_err(|_| INVALID)?.is_file() {
            return Err(INVALID.into());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            file.set_permissions(fs::Permissions::from_mode(0o600))
                .map_err(|_| "Could not restrict local credential file permissions")?;
        }
        let mut bytes = Vec::new();
        file.take(LIMIT + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| INVALID)?;
        if bytes.len() as u64 > LIMIT {
            return Err(INVALID.into());
        }
        // Never include parser details: malformed input may contain a credential.
        let data: CredentialFile = serde_json::from_slice(&bytes).map_err(|_| INVALID)?;
        validate(&data)?;
        Ok(data)
    }

    /// Migrate any legacy plaintext tokens in ``credentials.json`` into the OS
    /// secret backend atomically; on backend failure, roll back written keys
    /// and leave the legacy file untouched so pairing state is never lost.
    fn migrate_plaintext_entries(&self, data: &mut CredentialFile) {
        let pending: Vec<(String, String, String)> = data
            .credentials
            .iter()
            .filter(|(_, val)| !is_secret_ref(val))
            .map(|(id, plaintext)| {
                (
                    id.clone(),
                    make_secret_ref(SECRET_NAMESPACE, id),
                    plaintext.clone(),
                )
            })
            .collect();
        if pending.is_empty() {
            return;
        }
        let mut written_refs: Vec<(String, Option<String>)> = Vec::new();
        for (_, ref_key, plaintext) in &pending {
            let prev = self.backend.get(&self.service, ref_key).ok().flatten();
            if self.backend.set(&self.service, ref_key, plaintext).is_err() {
                self.rollback_backend_writes(&written_refs);
                return;
            }
            written_refs.push((ref_key.clone(), prev));
        }

        let mut migrated = CredentialFile {
            version: data.version,
            credentials: data.credentials.clone(),
        };
        for (id, ref_key, _) in &pending {
            migrated.credentials.insert(id.clone(), ref_key.clone());
        }
        if self.save(&migrated).is_ok() {
            *data = migrated;
        } else {
            self.rollback_backend_writes(&written_refs);
        }
    }

    fn rollback_backend_writes(&self, entries: &[(String, Option<String>)]) {
        for (ref_key, prev) in entries.iter().rev() {
            match prev {
                Some(old) => {
                    let _ = self.backend.set(&self.service, ref_key, old);
                }
                None => {
                    let _ = self.backend.delete(&self.service, ref_key);
                }
            }
        }
    }

    fn read(&self) -> Result<CredentialFile, String> {
        let mut data = self.read_raw()?;
        self.migrate_plaintext_entries(&mut data);
        Ok(data)
    }

    pub fn clear(&self) -> Result<(), String> {
        if let Ok(existing) = self.read_raw() {
            for (id, stored) in existing.credentials {
                let ref_key = if is_secret_ref(&stored) {
                    stored
                } else {
                    make_secret_ref(SECRET_NAMESPACE, &id)
                };
                let _ = self.backend.delete(&self.service, &ref_key);
            }
        }
        self.save(&CredentialFile {
            version: 1,
            credentials: BTreeMap::new(),
        })
    }

    fn save(&self, data: &CredentialFile) -> Result<(), String> {
        validate(data)?;
        magi_platform::private_data::protect_magi_data_root(&self.directory)?;
        let mut temporary = tempfile::Builder::new()
            .prefix(".credentials-")
            .tempfile_in(&self.directory)
            .map_err(|_| "Could not create local credential file")?;
        // Apply the current-user ACL before writing metadata, including on Windows.
        magi_platform::private_data::protect_magi_data_root(&self.directory)?;
        let bytes = serde_json::to_vec(data).map_err(|_| "Could not encode local credentials")?;
        temporary
            .write_all(&bytes)
            .and_then(|_| temporary.as_file().sync_all())
            .map_err(|_| "Could not save local connection credentials")?;
        temporary
            .persist(self.path())
            .map_err(|_| "Could not replace local credential file")?;
        #[cfg(unix)]
        fs::File::open(&self.directory)
            .and_then(|file| file.sync_all())
            .map_err(|_| "Could not sync local credential directory")?;
        Ok(())
    }

    pub fn get(&self, id: &str) -> Result<String, String> {
        let mut data = self.read()?;
        let stored = data.credentials.remove(id).ok_or_else(|| MISSING.to_string())?;
        if is_secret_ref(&stored) {
            return self
                .backend
                .get(&self.service, &stored)?
                .ok_or_else(|| MISSING.to_string());
        }
        Ok(stored)
    }

    pub fn put(&self, id: &str, credential: &str) -> Result<(), String> {
        uuid::Uuid::parse_str(id).map_err(|_| INVALID.to_string())?;
        super::validate_token(credential).map_err(|_| INVALID.to_string())?;
        let mut data = self.read()?;
        let ref_key = make_secret_ref(SECRET_NAMESPACE, id);
        let prev = self.backend.get(&self.service, &ref_key).ok().flatten();
        self.backend.set(&self.service, &ref_key, credential)?;
        data.credentials.insert(id.into(), ref_key.clone());
        if let Err(err) = self.save(&data) {
            self.rollback_backend_writes(&[(ref_key, prev)]);
            return Err(err);
        }
        Ok(())
    }

    pub fn remove(&self, id: &str) -> Result<(), String> {
        let mut data = self.read()?;
        if let Some(stored) = data.credentials.remove(id) {
            let ref_key = if is_secret_ref(&stored) {
                stored
            } else {
                make_secret_ref(SECRET_NAMESPACE, id)
            };
            self.save(&data)?;
            let _ = self.backend.delete(&self.service, &ref_key);
        }
        Ok(())
    }
}

fn validate(data: &CredentialFile) -> Result<(), String> {
    if data.version != 1 || data.credentials.len() > 16 {
        return Err(INVALID.into());
    }
    for (id, credential) in &data.credentials {
        uuid::Uuid::parse_str(id).map_err(|_| INVALID)?;
        let expected_ref = make_secret_ref(SECRET_NAMESPACE, id);
        if credential != &expected_ref {
            super::validate_token(credential).map_err(|_| INVALID)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use magi_platform::credentials::InMemorySecretBackend;

    #[test]
    fn credentials_survive_reopen_without_plaintext_on_disk_and_removal_preserves_others() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("connections");
        let store = CredentialStore::new(&directory);
        let first = uuid::Uuid::new_v4().to_string();
        let second = uuid::Uuid::new_v4().to_string();
        let first_secret = "a".repeat(64);
        let second_secret = "b".repeat(64);

        assert_eq!(store.get(&first).unwrap_err(), MISSING);
        assert!(!store.path().exists());
        store.put(&first, &first_secret).unwrap();
        store.put(&second, &second_secret).unwrap();

        let raw_on_disk = fs::read_to_string(store.path()).unwrap();
        assert!(!raw_on_disk.contains(&first_secret));
        assert!(!raw_on_disk.contains(&second_secret));
        assert!(raw_on_disk.contains(&make_secret_ref(SECRET_NAMESPACE, &first)));

        let reopened = CredentialStore::new(&directory);
        assert_eq!(reopened.get(&first).unwrap(), first_secret);
        reopened.remove(&first).unwrap();
        reopened.remove(&first).unwrap();
        assert_eq!(store.get(&first).unwrap_err(), MISSING);
        assert_eq!(store.get(&second).unwrap(), second_secret);
        assert!(!fs::read_to_string(store.path())
            .unwrap()
            .contains(&first_secret));
        assert!(!fs::read_to_string(store.path())
            .unwrap()
            .contains(&second_secret));
        assert_eq!(fs::read_dir(&directory).unwrap().count(), 1);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&directory).unwrap().permissions().mode() & 0o777,
                0o700
            );
            assert_eq!(
                fs::metadata(store.path()).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }

    #[test]
    fn legacy_plaintext_credentials_migrate_to_keychain_and_rollback_on_denial() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("connections");
        fs::create_dir(&directory).unwrap();
        let id = uuid::Uuid::new_v4().to_string();
        let legacy_token = "c".repeat(64);
        let legacy_json = format!(r#"{{"version":1,"credentials":{{"{id}":"{legacy_token}"}}}}"#);
        fs::write(directory.join("credentials.json"), &legacy_json).unwrap();

        // 1. Denied keychain write must preserve legacy file untouched and still allow reading
        let denied_backend = Arc::new(InMemorySecretBackend::new());
        denied_backend.set_fail_writes(true);
        let denied_store = CredentialStore::with_backend(&directory, denied_backend.clone());
        assert_eq!(denied_store.get(&id).unwrap(), legacy_token);
        assert_eq!(
            fs::read_to_string(directory.join("credentials.json")).unwrap(),
            legacy_json
        );
        assert!(denied_backend.is_empty());

        // 2. Working keychain migrates atomically and scrubs plaintext from disk
        let ok_backend = Arc::new(InMemorySecretBackend::new());
        let migrated_store = CredentialStore::with_backend(&directory, ok_backend.clone());
        assert_eq!(migrated_store.get(&id).unwrap(), legacy_token);
        let scrubbed_disk = fs::read_to_string(directory.join("credentials.json")).unwrap();
        assert!(!scrubbed_disk.contains(&legacy_token));
        assert!(scrubbed_disk.contains(&make_secret_ref(SECRET_NAMESPACE, &id)));
        assert_eq!(ok_backend.len(), 1);
    }

    #[test]
    fn invalid_input_is_not_leaked_or_overwritten() {
        let root = tempfile::tempdir().unwrap();
        let store = CredentialStore::new(root.path());
        let id = uuid::Uuid::new_v4().to_string();
        for bytes in [
            br#"{"version":2,"credentials":{}}"#.to_vec(),
            br#"{"secret-value-that-must-not-leak":true}"#.to_vec(),
            vec![b'x'; LIMIT as usize + 1],
        ] {
            fs::write(store.path(), &bytes).unwrap();
            assert_eq!(store.get(&id).unwrap_err(), INVALID);
            assert_eq!(store.put(&id, &"b".repeat(64)).unwrap_err(), INVALID);
            assert_eq!(fs::read(store.path()).unwrap(), bytes);
        }
        fs::remove_file(store.path()).unwrap();
        assert_eq!(store.put(&id, "too-short").unwrap_err(), INVALID);
        assert!(!store.path().exists());
    }

    #[cfg(unix)]
    #[test]
    fn linked_credential_files_are_rejected_without_touching_the_target() {
        use std::os::unix::fs::symlink;
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("connections");
        fs::create_dir(&directory).unwrap();
        let target = root.path().join("unrelated.json");
        fs::write(&target, b"unrelated").unwrap();
        let store = CredentialStore::new(&directory);
        let id = uuid::Uuid::new_v4().to_string();
        symlink(&target, store.path()).unwrap();
        assert!(store.put(&id, &"a".repeat(64)).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"unrelated");
        fs::remove_file(store.path()).unwrap();
        fs::hard_link(&target, store.path()).unwrap();
        assert!(store.get(&id).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"unrelated");
    }
}
