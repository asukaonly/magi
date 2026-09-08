//! Device-owned connection profiles and OS-vault credentials.

mod profiles;
pub mod protocol;
mod vault;

use std::path::Path;
use std::sync::{Arc, Mutex};

use profiles::ProfileStore;
pub use profiles::{Profile, ProfileFile};
pub use protocol::AccessSession;
use protocol::CenterClient;

pub struct Connections {
    store: Arc<Mutex<ProfileStore>>,
    operation: tokio::sync::Mutex<()>,
}

impl Connections {
    pub fn open(directory: &Path) -> Result<Self, String> {
        Ok(Self {
            store: Arc::new(Mutex::new(ProfileStore::open(directory)?)),
            operation: tokio::sync::Mutex::new(()),
        })
    }

    pub fn list(&self) -> ProfileFile {
        self.store
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .data
            .clone()
    }

    pub fn profile(&self, id: &str) -> Result<Profile, String> {
        self.store
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .profile(id)
    }

    pub async fn activate(&self, id: String) -> Result<(), String> {
        let _guard = self.operation.lock().await;
        let store = Arc::clone(&self.store);
        blocking(move || {
            let mut store = store.lock().unwrap_or_else(|e| e.into_inner());
            store.profile(&id)?;
            let mut data = store.data.clone();
            data.active_profile_id = Some(id);
            store.save(data)
        })
        .await
    }

    pub async fn pair(
        &self,
        address: String,
        token: String,
        name: String,
        device_name: String,
    ) -> Result<Profile, String> {
        let _guard = self.operation.lock().await;
        if !cfg!(any(target_os = "macos", windows)) {
            return Err("Remote credential storage is not supported on this platform".into());
        }
        let name = name.trim().to_owned();
        if name.is_empty() || name.len() > 128 || name.chars().any(char::is_control) {
            return Err("Enter a connection name of 1 to 128 bytes".into());
        }
        let device_name = device_name.trim();
        if device_name.is_empty()
            || device_name.len() > 128
            || device_name.chars().any(char::is_control)
        {
            return Err("Enter a device name of 1 to 128 bytes".into());
        }
        if self.list().profiles.len() >= 17 {
            return Err("Connection profile limit reached".into());
        }
        let address = protocol::normalize_remote_url(&address)?;
        let client = CenterClient::remote(&address)?;
        let grant = client.pair(token.trim(), device_name).await?;
        validate_token(&grant.client_credential)?;
        let access = client.renew(&grant.client_credential).await?;
        validate_session(&access, &grant.server_id, &grant.client_id)?;
        let info = client.info(&access.access_token).await?;
        if info.server_id != grant.server_id {
            return Err("Center identity changed while pairing".into());
        }
        let profile = Profile::Remote {
            id: uuid::Uuid::new_v4().to_string(),
            name,
            api_base_url: address,
            server_id: grant.server_id,
            client_id: grant.client_id,
        };
        let saved = profile.clone();
        let store = Arc::clone(&self.store);
        blocking(move || {
            vault::put(saved.id(), &grant.client_credential)?;
            let mut store = store.lock().unwrap_or_else(|e| e.into_inner());
            let mut data = store.data.clone();
            data.profiles.push(saved.clone());
            if let Err(error) = store.save(data) {
                let _ = vault::remove(saved.id());
                return Err(error);
            }
            Ok(())
        })
        .await?;
        Ok(profile)
    }

    pub async fn renew(&self, id: String) -> Result<AccessSession, String> {
        let _guard = self.operation.lock().await;
        let Profile::Remote {
            api_base_url,
            server_id,
            client_id,
            ..
        } = self.profile(&id)?
        else {
            return Err("Local connections use their process owner session".into());
        };
        let credential = blocking(move || vault::get(&id)).await?;
        let client = CenterClient::remote(&api_base_url)?;
        let session = client.renew(&credential).await?;
        validate_session(&session, &server_id, &client_id)?;
        let info = client.info(&session.access_token).await?;
        if info.server_id != server_id {
            return Err("Center identity changed; pair it as a new connection".into());
        }
        Ok(session)
    }

    pub async fn forget(&self, id: String) -> Result<(), String> {
        let _guard = self.operation.lock().await;
        if id == "local" {
            return Err("The local connection cannot be removed".into());
        }
        let store = Arc::clone(&self.store);
        blocking(move || {
            let mut store = store.lock().unwrap_or_else(|e| e.into_inner());
            store.profile(&id)?;
            vault::remove(&id)?;
            let mut data = store.data.clone();
            data.profiles.retain(|profile| profile.id() != id);
            if data.active_profile_id.as_deref() == Some(&id) {
                data.active_profile_id = None;
            }
            store.save(data)
        })
        .await
    }
}

fn validate_session(
    session: &AccessSession,
    server_id: &str,
    client_id: &str,
) -> Result<(), String> {
    if session.server_id != server_id || session.client_id != client_id {
        return Err("Center returned a different device identity".into());
    }
    uuid::Uuid::parse_str(server_id).map_err(|_| "Center identity is invalid")?;
    uuid::Uuid::parse_str(client_id).map_err(|_| "Device identity is invalid")?;
    validate_token(&session.access_token)
}

fn validate_token(token: &str) -> Result<(), String> {
    if token.len() < 32
        || token.len() > 256
        || !token.is_ascii()
        || token.chars().any(char::is_control)
    {
        return Err("Center returned an invalid credential".into());
    }
    Ok(())
}

async fn blocking<T: Send + 'static>(
    operation: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tokio::task::spawn_blocking(operation)
        .await
        .map_err(|_| "Connection storage operation failed".to_owned())?
}
