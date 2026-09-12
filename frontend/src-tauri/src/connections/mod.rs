//! Device-owned profiles and private-file credentials, with separate UI contracts.

mod credentials;
mod profiles;
pub mod protocol;
pub mod runtime;

use std::path::Path;
use std::sync::{Arc, Mutex};

use profiles::ProfileStore;
pub use profiles::{Profile, ProfileFile};
pub use protocol::AccessSession;
use protocol::CenterClient;

pub struct Connections {
    store: Arc<Mutex<ProfileStore>>,
    credentials: credentials::CredentialStore,
    operation: tokio::sync::Mutex<()>,
}

impl Connections {
    pub fn open(directory: &Path) -> Result<Self, String> {
        Ok(Self {
            store: Arc::new(Mutex::new(ProfileStore::open(directory)?)),
            credentials: credentials::CredentialStore::new(directory),
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
        let credentials = self.credentials.clone();
        blocking(move || {
            let mut store = store.lock().unwrap_or_else(|e| e.into_inner());
            if matches!(store.profile(&id)?, Profile::Remote { .. }) {
                credentials.get(&id)?;
            }
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
        if !cfg!(any(unix, windows)) {
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
        let credentials = self.credentials.clone();
        blocking(move || {
            credentials.put(saved.id(), &grant.client_credential)?;
            let mut store = store.lock().unwrap_or_else(|e| e.into_inner());
            let mut data = store.data.clone();
            data.profiles.push(saved.clone());
            if let Err(error) = store.save(data) {
                let _ = credentials.remove(saved.id());
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
        let credentials = self.credentials.clone();
        let credential = blocking(move || credentials.get(&id)).await?;
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
        let credentials = self.credentials.clone();
        blocking(move || {
            let mut store = store.lock().unwrap_or_else(|e| e.into_inner());
            store.profile(&id)?;
            credentials.remove(&id)?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[tokio::test]
    async fn pairing_persists_only_the_device_credential_and_reopen_renews_it() {
        use serde_json::json;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let root = tempfile::tempdir().unwrap();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = format!("http://{}", listener.local_addr().unwrap());
        let server_id = uuid::Uuid::new_v4().to_string();
        let client_id = uuid::Uuid::new_v4().to_string();
        let pair_code = "a".repeat(64);
        let device_key = "b".repeat(64);
        let session_key = "c".repeat(64);
        let access = json!({"server_id":server_id,"client_id":client_id,
            "access_token":session_key,"expires_at_ms":1});
        let info = json!({"server_id":server_id,
            "protocol_version":magi_service_contract::SERVER_PROTOCOL_VERSION,
            "service_ready":true,"maintenance":{"data_epoch":"data","content_epoch":"content","phase":"idle"}});
        let replies = [
            (
                "POST /api/auth/pair ",
                pair_code.clone(),
                json!({"server_id":server_id,
                "client_id":client_id,"client_credential":device_key}),
            ),
            (
                "POST /api/auth/session ",
                device_key.clone(),
                access.clone(),
            ),
            ("GET /api/server/info ", session_key.clone(), info.clone()),
            ("POST /api/auth/session ", device_key.clone(), access),
            ("GET /api/server/info ", session_key.clone(), info),
        ];
        let server = tokio::spawn(async move {
            for (path, token, data) in replies {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut headers = Vec::new();
                while !headers.windows(4).any(|part| part == b"\r\n\r\n") {
                    let mut buffer = [0; 1024];
                    let length = socket.read(&mut buffer).await.unwrap();
                    assert!(length > 0 && headers.len() + length <= 8192);
                    headers.extend_from_slice(&buffer[..length]);
                }
                let headers = String::from_utf8_lossy(&headers);
                assert!(headers.starts_with(path));
                assert!(headers.contains(&format!("x-magi-session-token: {token}\r\n")));
                let body = json!({"success":true,"data":data}).to_string();
                socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            }
        });
        let connections = Connections::open(root.path()).unwrap();
        let profile = connections
            .pair(address, pair_code.clone(), "Home".into(), "Desktop".into())
            .await
            .unwrap();
        let saved = fs::read_to_string(root.path().join("credentials.json")).unwrap();
        assert!(saved.contains(&device_key));
        assert!(!saved.contains(&pair_code));
        assert!(!saved.contains(&session_key));
        assert!(!serde_json::to_string(&connections.list())
            .unwrap()
            .contains(&device_key));
        drop(connections);
        let reopened = Connections::open(root.path()).unwrap();
        reopened.activate(profile.id().into()).await.unwrap();
        let session = reopened.renew(profile.id().into()).await.unwrap();
        assert_eq!(session.access_token, session_key);
        server.await.unwrap();
    }

    fn add_profile(connections: &Connections) -> String {
        let id = uuid::Uuid::new_v4().to_string();
        let mut store = connections.store.lock().unwrap();
        let mut data = store.data.clone();
        data.profiles.push(Profile::Remote {
            id: id.clone(),
            name: "Test center".into(),
            api_base_url: "http://127.0.0.1:19080/api".into(),
            server_id: uuid::Uuid::new_v4().to_string(),
            client_id: uuid::Uuid::new_v4().to_string(),
        });
        store.save(data).unwrap();
        id
    }

    #[tokio::test]
    async fn missing_credentials_require_pairing_and_can_be_forgotten() {
        let root = tempfile::tempdir().unwrap();
        let connections = Connections::open(root.path()).unwrap();
        let id = add_profile(&connections);
        assert_eq!(
            connections.activate(id.clone()).await.unwrap_err(),
            "local_credential_missing"
        );
        assert!(connections.list().active_profile_id.is_none());
        assert_eq!(
            connections.renew(id.clone()).await.err().unwrap(),
            "local_credential_missing"
        );
        connections.forget(id.clone()).await.unwrap();
        assert!(connections.profile(&id).is_err());
        assert!(!root.path().join("credentials.json").exists());
    }

    #[tokio::test]
    async fn forget_removes_native_credentials_and_active_selection() {
        let root = tempfile::tempdir().unwrap();
        let connections = Connections::open(root.path()).unwrap();
        let id = add_profile(&connections);
        let credential = "a".repeat(64);
        connections.credentials.put(&id, &credential).unwrap();
        connections.activate(id.clone()).await.unwrap();
        let reopened = Connections::open(root.path()).unwrap();
        assert_eq!(reopened.credentials.get(&id).unwrap(), credential);
        assert!(!serde_json::to_string(&reopened.list())
            .unwrap()
            .contains(&credential));
        assert!(!fs::read_to_string(root.path().join("connections.json"))
            .unwrap()
            .contains(&credential));
        reopened.forget(id.clone()).await.unwrap();
        assert!(reopened.list().active_profile_id.is_none());
        assert_eq!(
            reopened.credentials.get(&id).unwrap_err(),
            "local_credential_missing"
        );
        assert!(Connections::open(root.path())
            .unwrap()
            .profile(&id)
            .is_err());
    }
}
