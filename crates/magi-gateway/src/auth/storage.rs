use super::{ClientInfo, CollectorScope};
use rusqlite::{params, Connection, OptionalExtension};
use std::collections::HashMap;
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
        if version > 2 {
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
        if version < 2 {
            let transaction = connection.transaction().map_err(|e| e.to_string())?;
            transaction.execute_batch("CREATE TABLE collector_scopes (client_id TEXT PRIMARY KEY REFERENCES clients(client_id), connection_id TEXT NOT NULL, source_type TEXT NOT NULL); PRAGMA user_version=2;").map_err(|e|e.to_string())?;
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
        scope: Option<&CollectorScope>,
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
        let transaction = self.0.unchecked_transaction().map_err(|e| e.to_string())?;
        if let Some(scope) = scope {
            let existing: bool = transaction.query_row(
                "SELECT EXISTS(SELECT 1 FROM collector_scopes s JOIN clients c USING(client_id) WHERE s.connection_id=?1 AND s.source_type=?2 AND c.revoked_at_ms IS NULL)",
                params![scope.connection_id, scope.source_type], |row| row.get(0)
            ).map_err(|e| e.to_string())?;
            if existing {
                return Err(
                    "This source already has an active collector; revoke it before pairing another"
                        .into(),
                );
            }
        }
        transaction.execute("INSERT INTO clients (client_id, name, credential_hash, created_at_ms) VALUES (?1, ?2, ?3, ?4)",
            params![id, name, credential_hash, created]).map_err(|e| e.to_string())?;
        if let Some(scope) = scope {
            transaction
                .execute(
                    "INSERT INTO collector_scopes VALUES (?,?,?)",
                    params![id, scope.connection_id, scope.source_type],
                )
                .map_err(|e| e.to_string())?;
        }
        transaction.commit().map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn collector_scopes(&self) -> Result<HashMap<String, CollectorScope>, String> {
        let mut query = self
            .0
            .prepare("SELECT client_id,connection_id,source_type FROM collector_scopes")
            .map_err(|e| e.to_string())?;
        let rows = query
            .query_map([], |r| {
                Ok((
                    r.get(0)?,
                    CollectorScope {
                        connection_id: r.get(1)?,
                        source_type: r.get(2)?,
                    },
                ))
            })
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<_, _>>().map_err(|e| e.to_string())
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
        let mut statement = self.0.prepare("SELECT c.client_id, c.name, c.created_at_ms, c.revoked_at_ms, s.connection_id, s.source_type FROM clients c LEFT JOIN collector_scopes s ON s.client_id=c.client_id ORDER BY c.created_at_ms, c.client_id").map_err(|e| e.to_string())?;
        let rows = statement
            .query_map([], |row| {
                let connection_id: Option<String> = row.get(4)?;
                let collector_scope = match connection_id {
                    Some(connection_id) => Some(CollectorScope {
                        connection_id,
                        source_type: row.get(5)?,
                    }),
                    None => None,
                };
                Ok(ClientInfo {
                    client_id: row.get(0)?,
                    name: row.get(1)?,
                    created_at_ms: row.get(2)?,
                    revoked_at_ms: row.get(3)?,
                    role: if collector_scope.is_some() {
                        "collector"
                    } else {
                        "admin"
                    }
                    .into(),
                    collector_scope,
                })
            })
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())
    }
}
