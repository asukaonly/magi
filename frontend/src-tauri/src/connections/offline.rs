//! Native attestations for bounded, credential-free offline reading.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

use super::Profile;

const MAX_BYTES: u64 = 65_536;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OfflineConnection {
    pub version: u8,
    pub profile_id: String,
    pub mode: String,
    pub server_id: String,
    pub data_epoch: String,
    pub content_epoch: String,
    pub verified_at_ms: i64,
}

#[derive(Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
enum Binding {
    Local {
        data_root: PathBuf,
    },
    Remote {
        address: String,
        server_id: String,
        client_id: String,
    },
}

impl Binding {
    fn from_profile(profile: &Profile) -> Result<Self, String> {
        Ok(match profile {
            Profile::Local { .. } => Self::Local {
                data_root: crate::service_host::local_data_root()?
                    .canonicalize()
                    .map_err(|_| "Local data directory is unavailable")?,
            },
            Profile::Remote {
                api_base_url,
                server_id,
                client_id,
                ..
            } => Self::Remote {
                address: api_base_url.clone(),
                server_id: server_id.clone(),
                client_id: client_id.clone(),
            },
        })
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    binding: Binding,
    descriptor: OfflineConnection,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    version: u8,
    entries: BTreeMap<String, Entry>,
}

impl Default for Manifest {
    fn default() -> Self {
        Self {
            version: 1,
            entries: BTreeMap::new(),
        }
    }
}

#[derive(Clone)]
pub struct OfflineStore {
    directory: PathBuf,
    denied: Arc<Mutex<BTreeSet<String>>>,
    revision: Arc<AtomicU64>,
}

impl OfflineStore {
    pub fn new(directory: &Path) -> Self {
        Self {
            directory: directory.into(),
            denied: Default::default(),
            revision: Default::default(),
        }
    }
    pub fn revision(&self) -> u64 {
        self.revision.load(Ordering::Acquire)
    }

    fn path(&self) -> PathBuf {
        self.directory.join("offline-descriptors.json")
    }

    fn read(&self) -> Result<Manifest, String> {
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
                return Ok(Manifest::default())
            }
            Err(_) => return Err("offline_snapshot_unavailable".into()),
        };
        if !file
            .metadata()
            .map_err(|_| "offline_snapshot_unavailable")?
            .is_file()
        {
            return Err("offline_snapshot_unavailable".into());
        }
        let mut bytes = Vec::new();
        file.take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "offline_snapshot_unavailable")?;
        if bytes.len() as u64 > MAX_BYTES {
            return Err("offline_snapshot_unavailable".into());
        }
        let manifest: Manifest =
            serde_json::from_slice(&bytes).map_err(|_| "offline_snapshot_unavailable")?;
        if manifest.version != 1 || manifest.entries.len() > 17 {
            return Err("offline_snapshot_unavailable".into());
        }
        for (id, entry) in &manifest.entries {
            validate(&entry.descriptor)?;
            if id != &entry.descriptor.profile_id {
                return Err("offline_snapshot_unavailable".into());
            }
        }
        Ok(manifest)
    }

    fn save(&self, manifest: &Manifest) -> Result<(), String> {
        magi_platform::private_data::protect_magi_data_root(&self.directory)?;
        let mut temporary = tempfile::Builder::new()
            .prefix(".offline-")
            .tempfile_in(&self.directory)
            .map_err(|_| "offline_snapshot_unavailable")?;
        magi_platform::private_data::protect_magi_data_root(&self.directory)?;
        let bytes = serde_json::to_vec(manifest).map_err(|_| "offline_snapshot_unavailable")?;
        if bytes.len() as u64 > MAX_BYTES {
            return Err("offline_snapshot_unavailable".into());
        }
        temporary
            .write_all(&bytes)
            .and_then(|_| temporary.as_file().sync_all())
            .map_err(|_| "offline_snapshot_unavailable")?;
        temporary
            .persist(self.path())
            .map_err(|_| "offline_snapshot_unavailable")?;
        #[cfg(unix)]
        fs::File::open(&self.directory)
            .and_then(|file| file.sync_all())
            .map_err(|_| "offline_snapshot_unavailable")?;
        Ok(())
    }

    pub fn get(&self, profile: &Profile) -> Result<Option<OfflineConnection>, String> {
        if self
            .denied
            .lock()
            .map_err(|_| "Offline state unavailable")?
            .contains(profile.id())
        {
            return Ok(None);
        }
        let Some(entry) = self.read()?.entries.remove(profile.id()) else {
            return Ok(None);
        };
        if entry.binding != Binding::from_profile(profile)?
            || (entry.descriptor.mode == "local") != matches!(profile, Profile::Local { .. })
            || matches!(profile, Profile::Remote { server_id, .. } if server_id != &entry.descriptor.server_id)
        {
            return Ok(None);
        }
        Ok(Some(entry.descriptor))
    }

    pub fn record(&self, profile: &Profile, descriptor: OfflineConnection) -> Result<(), String> {
        validate(&descriptor)?;
        if descriptor.profile_id != profile.id()
            || matches!(profile, Profile::Remote { server_id, .. } if server_id != &descriptor.server_id)
            || (descriptor.mode == "local") != matches!(profile, Profile::Local { .. })
        {
            return Err("Offline connection identity mismatch".into());
        }
        // Only a fresh authenticated confirmation can replace an unreadable manifest.
        let mut manifest = self.read().unwrap_or_default();
        manifest.entries.insert(
            profile.id().into(),
            Entry {
                binding: Binding::from_profile(profile)?,
                descriptor,
            },
        );
        self.save(&manifest)?;
        self.denied
            .lock()
            .map_err(|_| "Offline state unavailable")?
            .remove(profile.id());
        Ok(())
    }

    pub fn remove(&self, profile_id: &str) -> Result<(), String> {
        self.revision.fetch_add(1, Ordering::AcqRel);
        // A failed disk invalidation must not restore known-revoked data in this process.
        self.denied
            .lock()
            .map_err(|_| "Offline state unavailable")?
            .insert(profile_id.into());
        let read = self.read();
        let reset = read.is_err();
        let mut manifest = read.unwrap_or_default();
        if manifest.entries.remove(profile_id).is_some() || reset {
            self.save(&manifest)?;
        }
        Ok(())
    }
}

fn validate(value: &OfflineConnection) -> Result<(), String> {
    if value.version != 1
        || value.verified_at_ms <= 0
        || !matches!(value.mode.as_str(), "local" | "remote")
        || (value.mode == "local" && value.profile_id != "local")
        || (value.mode == "remote" && uuid::Uuid::parse_str(&value.profile_id).is_err())
        || uuid::Uuid::parse_str(&value.server_id).is_err()
        || [&value.data_epoch, &value.content_epoch]
            .iter()
            .any(|epoch| {
                epoch.is_empty() || epoch.len() > 128 || epoch.chars().any(char::is_control)
            })
    {
        return Err("offline_snapshot_unavailable".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    pub(super) fn fixture() -> (Profile, OfflineConnection) {
        let profile = Profile::Remote {
            id: uuid::Uuid::new_v4().to_string(),
            name: "Center".into(),
            api_base_url: "https://center.example/api".into(),
            server_id: uuid::Uuid::new_v4().to_string(),
            client_id: uuid::Uuid::new_v4().to_string(),
        };
        let Profile::Remote { id, server_id, .. } = &profile else {
            unreachable!()
        };
        let descriptor = OfflineConnection {
            version: 1,
            profile_id: id.clone(),
            mode: "remote".into(),
            server_id: server_id.clone(),
            data_epoch: "data".into(),
            content_epoch: "content".into(),
            verified_at_ms: 123,
        };
        (profile, descriptor)
    }

    #[test]
    fn descriptor_roundtrip_has_no_credentials_and_is_bound_to_profile_identity() {
        let root = tempfile::tempdir().unwrap();
        let store = OfflineStore::new(root.path());
        let (profile, descriptor) = fixture();
        store.record(&profile, descriptor.clone()).unwrap();
        let reopened = OfflineStore::new(root.path());
        assert_eq!(reopened.get(&profile).unwrap(), Some(descriptor.clone()));
        let value = serde_json::to_value(&descriptor).unwrap();
        assert_eq!(value.as_object().unwrap().len(), 7);
        assert!(value.get("sessionToken").is_none());
        assert!(value.get("baseUrl").is_none());
        for field in ["api_base_url", "server_id", "client_id", "id"] {
            let mut changed = serde_json::to_value(&profile).unwrap();
            changed[field] = "changed".into();
            let changed: Profile = serde_json::from_value(changed).unwrap();
            assert!(reopened.get(&changed).unwrap().is_none(), "{field}");
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(store.path()).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }

    #[test]
    fn invalidation_persists_and_fresh_confirmation_is_required_to_restore() {
        let root = tempfile::tempdir().unwrap();
        let store = OfflineStore::new(root.path());
        let (profile, descriptor) = fixture();
        store.record(&profile, descriptor.clone()).unwrap();
        store.remove(profile.id()).unwrap();
        assert!(OfflineStore::new(root.path())
            .get(&profile)
            .unwrap()
            .is_none());
        store.record(&profile, descriptor.clone()).unwrap();
        assert_eq!(store.get(&profile).unwrap(), Some(descriptor));
    }

    #[test]
    fn failed_disk_invalidation_stays_denied_in_memory() {
        let root = tempfile::tempdir().unwrap();
        let store = OfflineStore::new(root.path());
        let (profile, descriptor) = fixture();
        store.record(&profile, descriptor.clone()).unwrap();
        let original = fs::read(store.path()).unwrap();
        fs::remove_file(store.path()).unwrap();
        fs::create_dir(store.path()).unwrap();
        assert!(store.remove(profile.id()).is_err());
        fs::remove_dir(store.path()).unwrap();
        fs::write(store.path(), original).unwrap();
        assert!(store.clone().get(&profile).unwrap().is_none());
        store.record(&profile, descriptor.clone()).unwrap();
        assert_eq!(store.get(&profile).unwrap(), Some(descriptor));
    }

    #[test]
    fn explicit_invalidation_and_confirmation_recover_corrupt_optional_storage() {
        let root = tempfile::tempdir().unwrap();
        let store = OfflineStore::new(root.path());
        let (profile, descriptor) = fixture();
        fs::write(store.path(), "corrupt").unwrap();
        assert!(store.get(&profile).is_err());
        store.remove(profile.id()).unwrap();
        assert!(store.get(&profile).unwrap().is_none());
        fs::write(store.path(), "corrupt again").unwrap();
        store.record(&profile, descriptor.clone()).unwrap();
        assert_eq!(store.get(&profile).unwrap(), Some(descriptor));
    }

    #[test]
    fn persisted_payload_rejects_invalid_epochs_and_oversized_or_unknown_data() {
        let root = tempfile::tempdir().unwrap();
        let store = OfflineStore::new(root.path());
        let (profile, mut descriptor) = fixture();
        descriptor.content_epoch.clear();
        assert!(store.record(&profile, descriptor).is_err());
        fs::write(store.path(), vec![b' '; MAX_BYTES as usize + 1]).unwrap();
        assert!(store.get(&profile).is_err());
        fs::write(store.path(), r#"{"version":2,"entries":{}}"#).unwrap();
        assert!(store.get(&profile).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn descriptor_file_rejects_symlink() {
        let root = tempfile::tempdir().unwrap();
        let outside = tempfile::NamedTempFile::new().unwrap();
        let store = OfflineStore::new(root.path());
        std::os::unix::fs::symlink(outside.path(), store.path()).unwrap();
        assert!(store.get(&fixture().0).is_err());
    }
}
