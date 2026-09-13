//! Per-client credentials and ephemeral sessions owned by the center.

mod storage;

use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::sync::{Mutex, RwLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use sha2::{Digest, Sha256};

const ACCESS_TTL: Duration = Duration::from_secs(15 * 60);
const PAIR_TTL: Duration = Duration::from_secs(30 * 60);
pub const LOCAL_OWNER: &str = "local-owner";

pub struct AuthStore {
    pub server_id: String,
    database: Mutex<storage::AuthDatabase>,
    memory: RwLock<Memory>,
}

#[derive(Default)]
struct Memory {
    active_clients: HashSet<String>,
    sessions: HashMap<String, Session>,
    grants: HashMap<String, Instant>,
    collector_grants: HashMap<String, CollectorScope>,
    collector_clients: HashMap<String, CollectorScope>,
}

#[derive(Clone, Debug, Serialize)]
pub struct CollectorScope {
    pub connection_id: String,
    pub source_type: String,
}

struct Session {
    client_id: String,
    expires_at: Option<Instant>,
}

#[derive(Clone, Debug, Serialize)]
pub struct ClientInfo {
    pub client_id: String,
    pub name: String,
    pub created_at_ms: i64,
    pub revoked_at_ms: Option<i64>,
    pub role: String,
    pub collector_scope: Option<CollectorScope>,
}

#[derive(Clone, Serialize)]
pub struct PairingGrant {
    pub pairing_token: String,
    pub expires_at_ms: i64,
    pub server_id: String,
}

#[derive(Clone, Serialize)]
pub struct ClientGrant {
    pub server_id: String,
    pub client_id: String,
    pub client_credential: String,
}

#[derive(Clone, Serialize)]
pub struct AccessSession {
    pub server_id: String,
    pub client_id: String,
    pub access_token: String,
    pub expires_at_ms: i64,
}

impl AuthStore {
    pub fn notification_policy(&self) -> Result<String, String> {
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .notification_policy()
    }
    pub fn set_notification_policy(&self, mode: &str) -> Result<(), String> {
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .set_notification_policy(mode)
    }
    pub fn claim_notification(
        &self,
        epoch: &str,
        notification: &str,
        client: &str,
    ) -> Result<bool, String> {
        if notification.is_empty() || notification.len() > 256 {
            return Err("Invalid notification identity".into());
        }
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .claim_notification(epoch, notification, client, now_ms())
    }

    pub fn open(path: &Path) -> Result<Self, String> {
        Self::from_database(storage::AuthDatabase::open(path)?)
    }

    pub fn local(token: &str) -> Self {
        let store = Self::from_database(
            storage::AuthDatabase::memory().expect("create local authentication store"),
        )
        .expect("initialize local authentication store");
        store.bootstrap_local_owner(token);
        store
    }

    fn from_database(database: storage::AuthDatabase) -> Result<Self, String> {
        let collector_clients = database.collector_scopes()?;
        let active_clients = database
            .clients()?
            .into_iter()
            .filter(|c| c.revoked_at_ms.is_none())
            .map(|c| c.client_id)
            .collect();
        Ok(Self {
            server_id: database.server_id()?,
            database: Mutex::new(database),
            memory: RwLock::new(Memory {
                active_clients,
                collector_clients,
                ..Memory::default()
            }),
        })
    }

    /// Only a private OS owner channel may create this process-lifetime session.
    pub fn bootstrap_local_owner(&self, token: &str) {
        assert!(
            !token.is_empty(),
            "local owner credential must not be empty"
        );
        let mut memory = self.memory.write().unwrap_or_else(|e| e.into_inner());
        memory.active_clients.insert(LOCAL_OWNER.into());
        memory.sessions.insert(
            hash(token),
            Session {
                client_id: LOCAL_OWNER.into(),
                expires_at: None,
            },
        );
    }

    /// Issue a bounded session only after authenticating the private OS operator channel.
    pub fn operator_session(&self) -> AccessSession {
        let mut memory = self.memory.write().unwrap_or_else(|e| e.into_inner());
        memory.active_clients.insert(LOCAL_OWNER.into());
        memory.sessions.retain(|_, session| {
            session
                .expires_at
                .is_none_or(|expiry| expiry > Instant::now())
        });
        let operator_sessions = memory.sessions.iter().filter(|(_, session)| {
            session.client_id == LOCAL_OWNER && session.expires_at.is_some()
        });
        if operator_sessions.clone().count() >= 8 {
            if let Some(oldest) = operator_sessions
                .min_by_key(|(_, session)| session.expires_at)
                .map(|(key, _)| key.clone())
            {
                memory.sessions.remove(&oldest);
            }
        }
        let token = random_token();
        memory.sessions.insert(
            hash(&token),
            Session {
                client_id: LOCAL_OWNER.into(),
                expires_at: Some(Instant::now() + ACCESS_TTL),
            },
        );
        AccessSession {
            server_id: self.server_id.clone(),
            client_id: LOCAL_OWNER.into(),
            access_token: token,
            expires_at_ms: now_ms() + ACCESS_TTL.as_millis() as i64,
        }
    }

    pub fn authenticate(&self, token: &str) -> Option<String> {
        if token.len() > 256 {
            return None;
        }
        let memory = self.memory.read().unwrap_or_else(|e| e.into_inner());
        memory
            .sessions
            .get(&hash(token))
            .filter(|s| {
                s.expires_at.is_none_or(|t| t > Instant::now())
                    && memory.active_clients.contains(&s.client_id)
            })
            .map(|s| s.client_id.clone())
    }

    pub fn client_is_active(&self, client_id: &str) -> bool {
        self.memory
            .read()
            .unwrap_or_else(|e| e.into_inner())
            .active_clients
            .contains(client_id)
    }

    pub fn create_pairing_grant(&self) -> Result<PairingGrant, String> {
        let mut memory = self.memory.write().unwrap_or_else(|e| e.into_inner());
        memory.grants.retain(|_, expires| *expires > Instant::now());
        let live: HashSet<_> = memory.grants.keys().cloned().collect();
        memory.collector_grants.retain(|key, _| live.contains(key));
        if memory.grants.len() >= 8 {
            return Err("Too many active pairing grants".into());
        }
        let token = random_token();
        memory
            .grants
            .insert(hash(&token), Instant::now() + PAIR_TTL);
        Ok(PairingGrant {
            pairing_token: token,
            expires_at_ms: now_ms() + PAIR_TTL.as_millis() as i64,
            server_id: self.server_id.clone(),
        })
    }

    pub fn create_collector_grant(
        &self,
        connection_id: String,
        source_type: String,
    ) -> Result<PairingGrant, String> {
        if !magi_service_contract::delivery::valid_connection_id(&connection_id)
            || !magi_service_contract::delivery::valid_key(&source_type)
        {
            return Err("Invalid collector scope".into());
        }
        let grant = self.create_pairing_grant()?;
        self.memory
            .write()
            .unwrap_or_else(|e| e.into_inner())
            .collector_grants
            .insert(
                hash(&grant.pairing_token),
                CollectorScope {
                    connection_id,
                    source_type,
                },
            );
        Ok(grant)
    }

    pub fn collector_scope(&self, client_id: &str) -> Option<CollectorScope> {
        self.memory
            .read()
            .unwrap_or_else(|e| e.into_inner())
            .collector_clients
            .get(client_id)
            .cloned()
    }

    pub fn validates_pairing_grant(&self, token: &str) -> bool {
        token.len() <= 256
            && self
                .memory
                .read()
                .unwrap_or_else(|e| e.into_inner())
                .grants
                .get(&hash(token))
                .is_some_and(|expires| *expires > Instant::now())
    }

    /// Single-use grant consumption precedes durable credential creation.
    pub fn pair(&self, token: &str, name: &str) -> Result<ClientGrant, String> {
        let name = name.trim();
        if name.is_empty() || name.len() > 128 || name.chars().any(char::is_control) {
            return Err(
                "Client name must contain 1 to 128 bytes without control characters".into(),
            );
        }
        if token.len() > 256 {
            return Err("Pairing grant is invalid or expired".into());
        }
        let (grant, scope) = {
            let mut memory = self.memory.write().unwrap_or_else(|e| e.into_inner());
            (
                memory.grants.remove(&hash(token)),
                memory.collector_grants.remove(&hash(token)),
            )
        };
        if !grant.is_some_and(|expires| expires > Instant::now()) {
            return Err("Pairing grant is invalid or expired".into());
        }
        let client_id = uuid::Uuid::new_v4().to_string();
        let credential = random_token();
        let database = self.database.lock().unwrap_or_else(|e| e.into_inner());
        database.insert_client(
            &client_id,
            name,
            &hash(&credential),
            now_ms(),
            scope.as_ref(),
        )?;
        if let Some(scope) = scope {
            self.memory
                .write()
                .unwrap_or_else(|e| e.into_inner())
                .collector_clients
                .insert(client_id.clone(), scope);
        }
        self.memory
            .write()
            .unwrap_or_else(|e| e.into_inner())
            .active_clients
            .insert(client_id.clone());
        Ok(ClientGrant {
            server_id: self.server_id.clone(),
            client_id,
            client_credential: credential,
        })
    }

    /// Credential lookup is an infrequent operation; call it on a blocking worker.
    pub fn renew(&self, credential: &str) -> Result<AccessSession, String> {
        if credential.len() > 256 {
            return Err("Client credential is invalid or revoked".into());
        }
        let database = self.database.lock().unwrap_or_else(|e| e.into_inner());
        let client_id = database
            .credential_client(&hash(credential))?
            .ok_or("Client credential is invalid or revoked")?;
        let mut memory = self.memory.write().unwrap_or_else(|e| e.into_inner());
        if !memory.active_clients.contains(&client_id) {
            return Err("Client credential is invalid or revoked".into());
        }
        memory
            .sessions
            .retain(|_, session| session.expires_at.is_none_or(|t| t > Instant::now()));
        if memory
            .sessions
            .values()
            .filter(|s| s.client_id == client_id)
            .count()
            >= 8
        {
            if let Some(oldest) = memory
                .sessions
                .iter()
                .filter(|(_, s)| s.client_id == client_id)
                .min_by_key(|(_, s)| s.expires_at)
                .map(|(key, _)| key.clone())
            {
                memory.sessions.remove(&oldest);
            }
        }
        let token = random_token();
        memory.sessions.insert(
            hash(&token),
            Session {
                client_id: client_id.clone(),
                expires_at: Some(Instant::now() + ACCESS_TTL),
            },
        );
        Ok(AccessSession {
            server_id: self.server_id.clone(),
            client_id,
            access_token: token,
            expires_at_ms: now_ms() + ACCESS_TTL.as_millis() as i64,
        })
    }

    pub fn clients(&self) -> Result<Vec<ClientInfo>, String> {
        self.database
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clients()
    }

    pub fn revoke(&self, client_id: &str) -> Result<(), String> {
        if client_id == LOCAL_OWNER {
            return Err("The local OS owner cannot be revoked remotely".into());
        }
        let database = self.database.lock().unwrap_or_else(|e| e.into_inner());
        database.revoke(client_id, now_ms())?;
        let mut memory = self.memory.write().unwrap_or_else(|e| e.into_inner());
        memory.active_clients.remove(client_id);
        memory
            .sessions
            .retain(|_, session| session.client_id != client_id);
        Ok(())
    }
}

fn hash(token: &str) -> String {
    format!("{:x}", Sha256::digest(token.as_bytes()))
}
fn random_token() -> String {
    crate::api::security::generate_session_token()
}
fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn notification_claims_arbitrate_concurrent_devices_and_policy_changes() {
        let store = std::sync::Arc::new(AuthStore::local("owner"));
        let threads: Vec<_> = (0..8)
            .map(|index| {
                let store = store.clone();
                std::thread::spawn(move || {
                    store
                        .claim_notification("epoch", "message", &format!("client-{index}"))
                        .unwrap()
                })
            })
            .collect();
        assert_eq!(
            threads
                .into_iter()
                .map(|thread| usize::from(thread.join().unwrap()))
                .sum::<usize>(),
            1
        );
        assert!(store
            .claim_notification("new-epoch", "message", "client-a")
            .unwrap());
        store.set_notification_policy("all_devices").unwrap();
        assert!(store
            .claim_notification("epoch", "another-message", "client-a")
            .unwrap());
        assert!(store
            .claim_notification("epoch", "another-message", "client-b")
            .unwrap());
        assert!(!store
            .claim_notification("epoch", "another-message", "client-a")
            .unwrap());
        assert!(store.set_notification_policy("unknown").is_err());
    }

    #[test]
    fn collector_scope_survives_restart_and_revocation() {
        let path =
            std::env::temp_dir().join(format!("magi-collector-auth-{}.db", uuid::Uuid::new_v4()));
        let store = AuthStore::open(&path).unwrap();
        let connection = "conn_11111111111111111111111111111111";
        let grant = store
            .create_collector_grant(connection.into(), "git_activity".into())
            .unwrap();
        let client = store.pair(&grant.pairing_token, "Collector").unwrap();
        assert_eq!(store.clients().unwrap()[0].role, "collector");
        let duplicate = store
            .create_collector_grant(connection.into(), "git_activity".into())
            .unwrap();
        assert!(store.pair(&duplicate.pairing_token, "Duplicate").is_err());
        drop(store);
        let store = AuthStore::open(&path).unwrap();
        let scope = store.collector_scope(&client.client_id).unwrap();
        assert_eq!(scope.connection_id, connection);
        assert_eq!(scope.source_type, "git_activity");
        let session = store.renew(&client.client_credential).unwrap();
        store.revoke(&client.client_id).unwrap();
        assert!(store.authenticate(&session.access_token).is_none());
        assert!(store.renew(&client.client_credential).is_err());
        drop(store);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn operator_sessions_expire_are_bounded_and_preserve_process_owner() {
        let store = AuthStore::local("guardian");
        let first = store.operator_session();
        assert_eq!(
            store.authenticate(&first.access_token).as_deref(),
            Some(LOCAL_OWNER)
        );
        assert!((now_ms()..=now_ms() + 900_000).contains(&first.expires_at_ms));
        for _ in 0..8 {
            store.operator_session();
        }
        assert!(store.authenticate(&first.access_token).is_none());
        assert_eq!(store.authenticate("guardian").as_deref(), Some(LOCAL_OWNER));
        assert_eq!(store.memory.read().unwrap().sessions.len(), 9);
        assert!(store.clients().unwrap().is_empty());
        let last = store.operator_session();
        store
            .memory
            .write()
            .unwrap()
            .sessions
            .get_mut(&hash(&last.access_token))
            .unwrap()
            .expires_at = Some(Instant::now() - Duration::from_secs(1));
        assert!(store.authenticate(&last.access_token).is_none());
    }

    #[test]
    fn pairing_grants_have_a_thirty_minute_deadline() {
        let store = AuthStore::local("owner");
        let before = now_ms();
        let grant = store.create_pairing_grant().unwrap();
        let after = now_ms();
        assert!((before + 1_800_000..=after + 1_800_000).contains(&grant.expires_at_ms));
        let expiry = store.memory.read().unwrap().grants[&hash(&grant.pairing_token)];
        let remaining = expiry.duration_since(Instant::now());
        assert!(remaining > Duration::from_secs(29 * 60));
        assert!(remaining <= Duration::from_secs(30 * 60));
        assert!(store.validates_pairing_grant(&grant.pairing_token));

        store.memory.write().unwrap().grants.insert(
            hash(&grant.pairing_token),
            Instant::now() - Duration::from_secs(1),
        );
        assert!(!store.validates_pairing_grant(&grant.pairing_token));
        assert!(store.pair(&grant.pairing_token, "Laptop").is_err());
    }

    #[test]
    fn pairing_is_single_use_and_credentials_are_distinct_from_sessions() {
        let store = AuthStore::local("owner");
        let grant = store.create_pairing_grant().unwrap();
        assert!(store.authenticate(&grant.pairing_token).is_none());
        let client = store.pair(&grant.pairing_token, "Laptop").unwrap();
        assert!(store.pair(&grant.pairing_token, "Other").is_err());
        assert!(store.authenticate(&client.client_credential).is_none());
        let session = store.renew(&client.client_credential).unwrap();
        assert_eq!(
            store.authenticate(&session.access_token),
            Some(client.client_id.clone())
        );
        store.revoke(&client.client_id).unwrap();
        assert!(store.authenticate(&session.access_token).is_none());
        assert!(store.renew(&client.client_credential).is_err());
        assert_eq!(store.authenticate("owner").as_deref(), Some(LOCAL_OWNER));
    }

    #[test]
    fn identity_and_revocation_survive_restart_but_sessions_do_not() {
        let path = std::env::temp_dir().join(format!("magi-auth-{}.db", uuid::Uuid::new_v4()));
        let store = AuthStore::open(&path).unwrap();
        let server_id = store.server_id.clone();
        let grant = store.create_pairing_grant().unwrap();
        let client = store.pair(&grant.pairing_token, "Desktop").unwrap();
        let session = store.renew(&client.client_credential).unwrap();
        drop(store);
        let store = AuthStore::open(&path).unwrap();
        assert_eq!(store.server_id, server_id);
        assert!(store.authenticate(&session.access_token).is_none());
        assert!(store.renew(&client.client_credential).is_ok());
        store.revoke(&client.client_id).unwrap();
        drop(store);
        let store = AuthStore::open(&path).unwrap();
        assert!(store.renew(&client.client_credential).is_err());
        drop(store);
        std::fs::remove_file(path).unwrap();
    }
}
