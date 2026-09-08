use super::ClientInfo;
use rusqlite::{params, Connection, OptionalExtension};
use std::path::Path;

pub(super) struct AuthDatabase(Connection);

impl AuthDatabase {
    pub fn open(path: &Path) -> Result<Self, String> {
        Self::initialize(Connection::open(path).map_err(|e| e.to_string())?)
    }

    pub fn memory() -> Result<Self, String> {
        Self::initialize(Connection::open_in_memory().map_err(|e| e.to_string())?)
    }

    fn initialize(mut connection: Connection) -> Result<Self, String> {
        connection
            .busy_timeout(std::time::Duration::from_secs(2))
            .map_err(|e| e.to_string())?;
        let version: i64 = connection
            .pragma_query_value(None, "user_version", |row| row.get(0))
            .map_err(|e| e.to_string())?;
        if version > 1 {
            return Err("Service authentication database requires a newer server".into());
        }
        if version == 0 {
            let transaction = connection.transaction().map_err(|e| e.to_string())?;
            transaction.execute_batch(
                "CREATE TABLE server_identity (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), server_id TEXT NOT NULL);
                 CREATE TABLE clients (client_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    credential_hash TEXT NOT NULL UNIQUE, created_at_ms INTEGER NOT NULL, revoked_at_ms INTEGER);
                 PRAGMA user_version = 1;"
            ).map_err(|e| e.to_string())?;
            transaction
                .execute(
                    "INSERT INTO server_identity (singleton, server_id) VALUES (1, ?1)",
                    [uuid::Uuid::new_v4().to_string()],
                )
                .map_err(|e| e.to_string())?;
            transaction.commit().map_err(|e| e.to_string())?;
        }
        Ok(Self(connection))
    }

    pub fn server_id(&self) -> Result<String, String> {
        self.0
            .query_row(
                "SELECT server_id FROM server_identity WHERE singleton = 1",
                [],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())
    }

    pub fn insert_client(
        &self,
        id: &str,
        name: &str,
        credential_hash: &str,
        created: i64,
    ) -> Result<(), String> {
        let count: i64 = self
            .0
            .query_row(
                "SELECT COUNT(*) FROM clients WHERE revoked_at_ms IS NULL",
                [],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        if count >= 64 {
            return Err("Active client limit reached".into());
        }
        self.0.execute("INSERT INTO clients (client_id, name, credential_hash, created_at_ms) VALUES (?1, ?2, ?3, ?4)",
            params![id, name, credential_hash, created]).map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn credential_client(&self, credential_hash: &str) -> Result<Option<String>, String> {
        self.0.query_row("SELECT client_id FROM clients WHERE credential_hash = ?1 AND revoked_at_ms IS NULL",
            [credential_hash], |row| row.get(0)).optional().map_err(|e| e.to_string())
    }

    pub fn revoke(&self, client_id: &str, at: i64) -> Result<(), String> {
        let changed = self.0.execute("UPDATE clients SET revoked_at_ms = COALESCE(revoked_at_ms, ?1) WHERE client_id = ?2",
            params![at, client_id]).map_err(|e| e.to_string())?;
        if changed == 0 {
            return Err("Client does not exist".into());
        }
        Ok(())
    }

    pub fn clients(&self) -> Result<Vec<ClientInfo>, String> {
        let mut statement = self.0.prepare("SELECT client_id, name, created_at_ms, revoked_at_ms FROM clients ORDER BY created_at_ms, client_id").map_err(|e| e.to_string())?;
        let rows = statement
            .query_map([], |row| {
                Ok(ClientInfo {
                    client_id: row.get(0)?,
                    name: row.get(1)?,
                    created_at_ms: row.get(2)?,
                    revoked_at_ms: row.get(3)?,
                })
            })
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())
    }
}
