//! Device credentials stored privately by the native desktop host.

use std::collections::BTreeMap;
#[cfg(any(unix, test))]
use std::fs;
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

const INVALID: &str = "local_credentials_invalid";
const MISSING: &str = "local_credential_missing";
const LIMIT: u64 = 65_536;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CredentialFile {
    version: u8,
    credentials: BTreeMap<String, String>,
}

#[derive(Clone)]
pub struct CredentialStore {
    directory: PathBuf,
}

impl CredentialStore {
    pub fn new(directory: &Path) -> Self {
        Self {
            directory: directory.into(),
        }
    }

    fn path(&self) -> PathBuf {
        self.directory.join("credentials.json")
    }

    fn read(&self) -> Result<CredentialFile, String> {
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

    fn save(&self, data: &CredentialFile) -> Result<(), String> {
        validate(data)?;
        magi_platform::private_data::protect_magi_data_root(&self.directory)?;
        let mut temporary = tempfile::Builder::new()
            .prefix(".credentials-")
            .tempfile_in(&self.directory)
            .map_err(|_| "Could not create local credential file")?;
        // Apply the current-user ACL before writing secrets, including on Windows.
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
        self.read()?
            .credentials
            .remove(id)
            .ok_or_else(|| MISSING.into())
    }

    pub fn put(&self, id: &str, credential: &str) -> Result<(), String> {
        let mut data = self.read()?;
        data.credentials.insert(id.into(), credential.into());
        self.save(&data)
    }

    pub fn remove(&self, id: &str) -> Result<(), String> {
        let mut data = self.read()?;
        if data.credentials.remove(id).is_some() {
            self.save(&data)?;
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
        super::validate_token(credential).map_err(|_| INVALID)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn credentials_survive_reopen_and_removal_preserves_other_connections() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("connections");
        let store = CredentialStore::new(&directory);
        let first = uuid::Uuid::new_v4().to_string();
        let second = uuid::Uuid::new_v4().to_string();
        assert_eq!(store.get(&first).unwrap_err(), MISSING);
        assert!(!store.path().exists());
        store.put(&first, &"a".repeat(64)).unwrap();
        store.put(&second, &"b".repeat(64)).unwrap();
        let reopened = CredentialStore::new(&directory);
        assert_eq!(reopened.get(&first).unwrap(), "a".repeat(64));
        reopened.remove(&first).unwrap();
        reopened.remove(&first).unwrap();
        assert_eq!(store.get(&first).unwrap_err(), MISSING);
        assert_eq!(store.get(&second).unwrap(), "b".repeat(64));
        assert!(!fs::read_to_string(store.path())
            .unwrap()
            .contains(&"a".repeat(64)));
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
