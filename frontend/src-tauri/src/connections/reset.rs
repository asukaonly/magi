//! Device-only reset. The marker keeps interrupted cleanup out of normal startup.

use super::{blocking, Connections, Profile, ProfileFile};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::sync::atomic::Ordering;

impl Connections {
    pub fn reset_pending(&self) -> bool {
        self.resetting.load(Ordering::Acquire)
    }

    pub fn require_available(&self) -> Result<(), String> {
        if self.reset_pending() {
            Err("Client reset must finish first".into())
        } else {
            Ok(())
        }
    }

    pub(super) fn require_pair_revision(&self, revision: u64) -> Result<(), String> {
        self.require_available()?;
        if self.reset_revision.load(Ordering::Acquire) != revision {
            return Err("Client was reset during pairing".into());
        }
        Ok(())
    }

    fn write_reset_marker(&self, phase: &[u8]) -> Result<(), String> {
        let mut options = OpenOptions::new();
        options.write(true).create(true).truncate(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
        }
        let mut file = options
            .open(&self.reset_path)
            .map_err(|_| "Could not save client reset state")?;
        file.write_all(phase)
            .and_then(|_| file.sync_all())
            .map_err(|_| "Could not save client reset state")?;
        self.sync_reset_directory()?;
        Ok(())
    }

    fn sync_reset_directory(&self) -> Result<(), String> {
        #[cfg(unix)]
        fs::File::open(
            self.reset_path
                .parent()
                .ok_or("Client directory is unavailable")?,
        )
        .and_then(|directory| directory.sync_all())
        .map_err(|_| "Could not persist client reset state")?;
        Ok(())
    }

    pub async fn begin_reset(&self) -> Result<(), String> {
        let _guard = self.operation.lock().await;
        self.write_reset_marker(b"pending")?;
        self.resetting.store(true, Ordering::Release);
        self.reset_revision.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }

    pub async fn clear_for_reset(&self) -> Result<(), String> {
        let _guard = self.operation.lock().await;
        if !self.reset_pending() {
            return Err("Client reset has not started".into());
        }
        let store = self.store.clone();
        let offline = self.offline.clone();
        let credentials = self.credentials.clone();
        blocking(move || {
            // Stop remembered connections first, including on a later process restart.
            store
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .save(ProfileFile {
                    version: 1,
                    active_profile_id: None,
                    profiles: vec![Profile::Local { id: "local".into() }],
                })?;
            offline.clear()?;
            credentials.clear()
        })
        .await
    }

    pub fn mark_reset_cleared(&self) -> Result<(), String> {
        self.write_reset_marker(b"native-cleared")
    }

    pub async fn complete_reset(&self) -> Result<(), String> {
        let _guard = self.operation.lock().await;
        if !self.reset_pending()
            || fs::read(&self.reset_path).map_err(|_| "Could not read client reset state")?
                != b"native-cleared"
        {
            return Err("Client reset has not finished".into());
        }
        fs::remove_file(&self.reset_path).map_err(|_| "Could not finish client reset")?;
        self.sync_reset_directory()?;
        self.resetting.store(false, Ordering::Release);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::super::offline::OfflineConnection;
    use super::*;

    #[tokio::test]
    async fn reset_clears_all_device_identities_and_survives_interruption() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("desktop");
        let service = root.path().join("service");
        fs::create_dir(&service).unwrap();
        fs::write(service.join("chat.db"), b"keep service data").unwrap();
        let connections = Connections::open(&directory).unwrap();
        let profile = Profile::Remote {
            id: uuid::Uuid::new_v4().to_string(),
            name: "Server".into(),
            api_base_url: "https://magi.example/api".into(),
            server_id: uuid::Uuid::new_v4().to_string(),
            client_id: uuid::Uuid::new_v4().to_string(),
        };
        let server_id = match &profile {
            Profile::Remote { server_id, .. } => server_id.clone(),
            _ => unreachable!(),
        };
        let mut profiles = connections.list();
        profiles.active_profile_id = Some(profile.id().into());
        profiles.profiles.push(profile.clone());
        connections.store.lock().unwrap().save(profiles).unwrap();
        connections
            .credentials
            .put(profile.id(), &"a".repeat(64))
            .unwrap();
        connections
            .offline
            .record(
                &profile,
                OfflineConnection {
                    version: 1,
                    profile_id: profile.id().into(),
                    mode: "remote".into(),
                    server_id,
                    data_epoch: uuid::Uuid::new_v4().to_string(),
                    content_epoch: uuid::Uuid::new_v4().to_string(),
                    verified_at_ms: 1,
                },
            )
            .unwrap();
        connections.begin_reset().await.unwrap();
        assert!(connections.activate("local".into()).await.is_err());
        assert!(connections.complete_reset().await.is_err());
        // Existing corrupt credential contents must not prevent explicitly discarding them.
        fs::write(directory.join("credentials.json"), b"broken secret file").unwrap();
        connections.clear_for_reset().await.unwrap();
        drop(connections);
        let reopened = Connections::open(&directory).unwrap();
        assert!(reopened.reset_pending());
        assert!(reopened.list().active_profile_id.is_none());
        assert_eq!(reopened.list().profiles.len(), 1);
        assert!(reopened.credentials.get(profile.id()).is_err());
        assert!(reopened.offline.get(&profile).unwrap().is_none());
        reopened.clear_for_reset().await.unwrap();
        reopened.mark_reset_cleared().unwrap();
        reopened.complete_reset().await.unwrap();
        assert!(!Connections::open(&directory).unwrap().reset_pending());
        assert_eq!(
            fs::read(service.join("chat.db")).unwrap(),
            b"keep service data"
        );
    }

    #[tokio::test]
    async fn delayed_pairing_cannot_restore_credentials_after_reset() {
        let root = tempfile::tempdir().unwrap();
        let connections = Connections::open(root.path()).unwrap();
        let revision = connections.reset_revision.load(Ordering::Acquire);
        connections.begin_reset().await.unwrap();
        assert!(connections.require_pair_revision(revision).is_err());
        connections.clear_for_reset().await.unwrap();
        connections.mark_reset_cleared().unwrap();
        connections.complete_reset().await.unwrap();
        assert!(connections.require_pair_revision(revision).is_err());
        assert!(connections
            .require_pair_revision(connections.reset_revision.load(Ordering::Acquire))
            .is_ok());
    }

    #[tokio::test]
    async fn failed_cleanup_keeps_reset_pending_and_can_be_retried() {
        let root = tempfile::tempdir().unwrap();
        let connections = Connections::open(root.path()).unwrap();
        fs::create_dir(root.path().join("credentials.json")).unwrap();
        connections.begin_reset().await.unwrap();
        assert!(connections.clear_for_reset().await.is_err());
        assert!(connections.reset_pending());
        assert!(connections.complete_reset().await.is_err());
        fs::remove_dir(root.path().join("credentials.json")).unwrap();
        connections.clear_for_reset().await.unwrap();
        connections.mark_reset_cleared().unwrap();
        connections.complete_reset().await.unwrap();
    }
}
