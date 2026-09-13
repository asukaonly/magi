//! Producer-owned durable delivery. SQLite is private to this queue, never a center database.

use magi_service_contract::delivery::{
    valid_key, BackgroundEvent, BackgroundPayload, DeliveryBatch, DeliveryReceipt, ReceiptStatus,
    MAX_BATCH_EVENTS,
};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::{path::Path, time::Duration};

const MAX_ROWS: i64 = 10_000;
const MAX_BYTES: i64 = 64 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    pub profile_id: String,
    pub server_id: String,
    pub data_epoch: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DeliveryPolicy {
    Reliable,
    Latest,
    BestEffort,
}

impl DeliveryPolicy {
    fn key(self) -> &'static str {
        match self {
            Self::Reliable => "reliable",
            Self::Latest => "latest",
            Self::BestEffort => "best_effort",
        }
    }
}

#[derive(Default, Debug, Serialize)]
pub struct QueueStatus {
    pub pending: i64,
    pub failed: i64,
    pub bytes: i64,
    pub next_retry_at_ms: Option<i64>,
    pub last_error: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct StreamStatus {
    pub stream: String,
    pub connection_id: Option<String>,
    pub plugin_target: Option<String>,
    pub pending: i64,
    pub failed: i64,
    pub oldest_at_ms: i64,
    pub attempts: i64,
    pub next_retry_at_ms: Option<i64>,
    pub last_error: Option<String>,
}

pub struct Outbox {
    db: Connection,
    _lease: magi_platform::instance::InstanceLease,
}

fn error(_: rusqlite::Error) -> String {
    "Background delivery storage failed".into()
}
fn valid_uuid(value: &str) -> bool {
    uuid::Uuid::parse_str(value).is_ok_and(|id| id.to_string() == value)
}

impl Outbox {
    pub fn open(directory: &Path) -> Result<Self, String> {
        magi_platform::private_data::protect_magi_data_root(directory)?;
        let lease =
            magi_platform::instance::InstanceLease::acquire(&directory.join("outbox.lock"))?;
        let path = directory.join("outbox.db");
        // Create inside a protected directory before opening SQLite and its sidecars.
        if !path.exists() {
            std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
                .map_err(|_| "Could not create delivery storage")?;
        }
        magi_platform::private_data::protect_magi_data_root(directory)?;
        let db = Connection::open(&path).map_err(error)?;
        db.busy_timeout(Duration::from_secs(2)).map_err(error)?;
        let initialized: bool = db
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='metadata')",
                [],
                |row| row.get(0),
            )
            .map_err(error)?;
        if initialized {
            let version: String = db
                .query_row(
                    "SELECT value FROM metadata WHERE key='version'",
                    [],
                    |row| row.get(0),
                )
                .map_err(error)?;
            if version != "1" {
                return Err("Unsupported delivery storage version".into());
            }
        }
        db.execute_batch("PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS streams (profile TEXT NOT NULL, server TEXT NOT NULL, epoch TEXT NOT NULL, stream TEXT NOT NULL, next_sequence INTEGER NOT NULL, PRIMARY KEY(profile,server,epoch,stream));
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, profile TEXT NOT NULL, server TEXT NOT NULL, epoch TEXT NOT NULL, stream TEXT NOT NULL, sequence INTEGER NOT NULL, occurred INTEGER NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL, policy TEXT NOT NULL, expires INTEGER, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, due INTEGER NOT NULL DEFAULT 0, lease INTEGER NOT NULL DEFAULT 0, last_error TEXT, UNIQUE(profile,server,epoch,stream,sequence));
            CREATE INDEX IF NOT EXISTS events_scope ON events(profile,server,epoch,stream,sequence);
            INSERT OR IGNORE INTO metadata VALUES ('version','1');").map_err(error)?;
        // The desktop owns one instance; leases from an exited process have no live requests.
        db.execute("UPDATE events SET lease=0", []).map_err(error)?;
        Ok(Self { db, _lease: lease })
    }

    pub fn enqueue(
        &mut self,
        scope: &Scope,
        stream: &str,
        id: &str,
        payload: BackgroundPayload,
        policy: DeliveryPolicy,
        now: i64,
    ) -> Result<bool, String> {
        if !valid_uuid(&scope.server_id)
            || !valid_uuid(&scope.data_epoch)
            || !valid_uuid(id)
            || !valid_key(stream)
            || !valid_key(&scope.profile_id)
            || now < 0
        {
            return Err("Invalid background delivery identity".into());
        }
        payload.validate()?;
        let body =
            serde_json::to_string(&payload).map_err(|_| "Invalid background delivery payload")?;
        let tx = self.db.transaction().map_err(error)?;
        let existing: Option<(String, String, String, String, String)> = tx
            .query_row(
                "SELECT profile,server,epoch,stream,payload FROM events WHERE id=?",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
            )
            .optional()
            .map_err(error)?;
        if let Some(value) = existing {
            return if value
                == (
                    scope.profile_id.clone(),
                    scope.server_id.clone(),
                    scope.data_epoch.clone(),
                    stream.into(),
                    body,
                ) {
                Ok(true)
            } else {
                Err("Delivery identity was reused for different content".into())
            };
        }
        tx.execute(
            "DELETE FROM events WHERE expires IS NOT NULL AND expires<=? AND lease<=?",
            params![now, now],
        )
        .map_err(error)?;
        if policy == DeliveryPolicy::Latest {
            tx.execute("DELETE FROM events WHERE profile=? AND server=? AND epoch=? AND stream=? AND policy='latest' AND lease<=?", params![scope.profile_id,scope.server_id,scope.data_epoch,stream,now]).map_err(error)?;
        }
        let stream_exists: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM streams WHERE profile=? AND server=? AND epoch=? AND stream=?)", params![scope.profile_id,scope.server_id,scope.data_epoch,stream], |r| r.get(0)).map_err(error)?;
        let stream_count: i64 = tx
            .query_row("SELECT COUNT(*) FROM streams", [], |r| r.get(0))
            .map_err(error)?;
        if !stream_exists && stream_count >= MAX_ROWS {
            return Err("Background stream capacity exhausted".into());
        }
        let (rows, bytes): (i64, i64) = tx
            .query_row(
                "SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM events",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .map_err(error)?;
        if rows >= MAX_ROWS || bytes + body.len() as i64 > MAX_BYTES {
            if policy == DeliveryPolicy::BestEffort {
                tx.commit().map_err(error)?;
                return Ok(false);
            }
            return Err("Background delivery queue is full; pause collection".into());
        }
        tx.execute("INSERT INTO streams VALUES (?1,?2,?3,?4,1) ON CONFLICT(profile,server,epoch,stream) DO UPDATE SET next_sequence=next_sequence+1", params![scope.profile_id,scope.server_id,scope.data_epoch,stream]).map_err(error)?;
        let sequence: i64 = tx.query_row("SELECT next_sequence FROM streams WHERE profile=? AND server=? AND epoch=? AND stream=?", params![scope.profile_id,scope.server_id,scope.data_epoch,stream], |r| r.get(0)).map_err(error)?;
        let expires = match policy {
            DeliveryPolicy::Reliable | DeliveryPolicy::Latest => None,
            DeliveryPolicy::BestEffort => Some(now + 3_600_000),
        };
        tx.execute("INSERT INTO events(id,profile,server,epoch,stream,sequence,occurred,payload,bytes,policy,expires) VALUES (?,?,?,?,?,?,?,?,?,?,?)", params![id,scope.profile_id,scope.server_id,scope.data_epoch,stream,sequence,now,body,body.len() as i64,policy.key(),expires]).map_err(error)?;
        tx.commit().map_err(error)?;
        Ok(true)
    }

    pub fn claim(&mut self, scope: &Scope, now: i64) -> Result<DeliveryBatch, String> {
        let tx = self.db.transaction().map_err(error)?;
        let producer_key = format!("producer:{}", scope.profile_id);
        tx.execute(
            "INSERT OR IGNORE INTO metadata VALUES (?,?)",
            params![producer_key, uuid::Uuid::new_v4().to_string()],
        )
        .map_err(error)?;
        let producer_id: String = tx
            .query_row(
                "SELECT value FROM metadata WHERE key=?",
                [producer_key],
                |row| row.get(0),
            )
            .map_err(error)?;

        tx.execute(
            "DELETE FROM events WHERE expires IS NOT NULL AND expires<=? AND lease<=?",
            params![now, now],
        )
        .map_err(error)?;
        let mut statement = tx.prepare("SELECT id,stream,sequence,occurred,payload FROM events e WHERE profile=?1 AND server=?2 AND epoch=?3 AND state='pending' AND due<=?4 AND lease<=?4 AND NOT EXISTS (SELECT 1 FROM events old WHERE old.profile=e.profile AND old.server=e.server AND old.epoch=e.epoch AND old.stream=e.stream AND old.sequence<e.sequence) ORDER BY due,occurred,id LIMIT ?5").map_err(error)?;
        let rows = statement
            .query_map(
                params![
                    scope.profile_id,
                    scope.server_id,
                    scope.data_epoch,
                    now,
                    MAX_BATCH_EVENTS as i64
                ],
                |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, i64>(2)?,
                        r.get::<_, i64>(3)?,
                        r.get::<_, String>(4)?,
                    ))
                },
            )
            .map_err(error)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(error)?;
        drop(statement);
        let mut events = Vec::new();
        for (event_id, stream, sequence, occurred_at_ms, payload) in rows {
            let payload =
                serde_json::from_str(&payload).map_err(|_| "Stored background event is invalid")?;
            tx.execute(
                "UPDATE events SET lease=? WHERE id=?",
                params![now + 60_000, event_id],
            )
            .map_err(error)?;
            events.push(BackgroundEvent {
                event_id,
                stream,
                sequence,
                occurred_at_ms,
                payload,
            });
        }
        tx.commit().map_err(error)?;
        Ok(DeliveryBatch {
            server_id: scope.server_id.clone(),
            data_epoch: scope.data_epoch.clone(),
            producer_id,
            events,
        })
    }

    pub fn acknowledge(
        &mut self,
        batch: &DeliveryBatch,
        receipt: &DeliveryReceipt,
        now: i64,
    ) -> Result<(), String> {
        let expected: std::collections::HashSet<_> =
            batch.events.iter().map(|e| &e.event_id).collect();
        let actual: std::collections::HashSet<_> =
            receipt.receipts.iter().map(|r| &r.event_id).collect();
        if receipt.server_id != batch.server_id
            || receipt.data_epoch != batch.data_epoch
            || expected != actual
            || actual.len() != receipt.receipts.len()
        {
            return Err("Invalid background delivery receipt".into());
        }
        let tx = self.db.transaction().map_err(error)?;
        for result in &receipt.receipts {
            let event = batch
                .events
                .iter()
                .find(|event| event.event_id == result.event_id)
                .ok_or("Invalid background delivery receipt")?;
            if !matches_stored_event(&tx, batch, event)? {
                continue;
            }
            match result.status {
                ReceiptStatus::Accepted => {
                    tx.execute("DELETE FROM events WHERE id=?", [&result.event_id])
                        .map_err(error)?;
                }
                ReceiptStatus::Rejected => {
                    tx.execute(
                        "UPDATE events SET state='failed',lease=0,last_error=? WHERE id=?",
                        params![safe_code(&result.code), result.event_id],
                    )
                    .map_err(error)?;
                }
                ReceiptStatus::Retry => {
                    retry_row(&tx, &result.event_id, now, &result.code, None)?;
                }
            }
        }
        // Notification IDs form independent coalescing keys, not long-lived source cursors.
        for event in &batch.events {
            if matches!(event.payload, BackgroundPayload::NotificationRead { .. }) {
                tx.execute("DELETE FROM streams WHERE server=? AND epoch=? AND stream=? AND NOT EXISTS (SELECT 1 FROM events e WHERE e.profile=streams.profile AND e.server=streams.server AND e.epoch=streams.epoch AND e.stream=streams.stream)", params![batch.server_id,batch.data_epoch,event.stream]).map_err(error)?;
            }
        }
        tx.commit().map_err(error)
    }

    pub fn retry(
        &mut self,
        batch: &DeliveryBatch,
        now: i64,
        code: &str,
        retry_after_ms: Option<i64>,
    ) -> Result<(), String> {
        let tx = self.db.transaction().map_err(error)?;
        for event in &batch.events {
            if matches_stored_event(&tx, batch, event)? {
                retry_row(&tx, &event.event_id, now, code, retry_after_ms)?;
            }
        }
        tx.commit().map_err(error)
    }

    pub fn retire_epochs(&self, profile: &str, server: &str, epoch: &str) -> Result<(), String> {
        self.db
            .execute(
                "DELETE FROM events WHERE profile=? AND (server<>? OR epoch<>?)",
                params![profile, server, epoch],
            )
            .map_err(error)?;
        self.db
            .execute(
                "DELETE FROM streams WHERE profile=? AND (server<>? OR epoch<>?)",
                params![profile, server, epoch],
            )
            .map_err(error)?;
        Ok(())
    }

    pub fn forget(&self, profile: &str) -> Result<(), String> {
        self.db
            .execute(
                "DELETE FROM metadata WHERE key=?",
                [format!("producer:{profile}")],
            )
            .map_err(error)?;
        self.db
            .execute("DELETE FROM events WHERE profile=?", [profile])
            .map_err(error)?;
        self.db
            .execute("DELETE FROM streams WHERE profile=?", [profile])
            .map_err(error)?;
        Ok(())
    }

    pub fn status(&self, scope: &Scope) -> Result<QueueStatus, String> {
        self.db.query_row("SELECT COALESCE(SUM(state='pending'),0),COALESCE(SUM(state='failed'),0),COALESCE(SUM(bytes),0),MIN(CASE WHEN state='pending' THEN due END),MAX(last_error) FROM events WHERE profile=? AND server=? AND epoch=?", params![scope.profile_id,scope.server_id,scope.data_epoch], |r| Ok(QueueStatus { pending:r.get(0)?,failed:r.get(1)?,bytes:r.get(2)?,next_retry_at_ms:r.get(3)?,last_error:r.get(4)? })).map_err(error)
    }

    pub fn has_work(&self, profile: &str, now: i64) -> Result<bool, String> {
        self.db.query_row("SELECT EXISTS(SELECT 1 FROM events e WHERE profile=? AND state='pending' AND due<=? AND lease<=? AND NOT EXISTS (SELECT 1 FROM events old WHERE old.profile=e.profile AND old.server=e.server AND old.epoch=e.epoch AND old.stream=e.stream AND old.sequence<e.sequence))", params![profile,now,now], |row| row.get(0)).map_err(error)
    }

    pub fn defer_profile(&self, profile: &str, now: i64, code: &str) -> Result<(), String> {
        self.db.execute("UPDATE events SET attempts=attempts+1,due=? + MIN(300000,1000*(1 << MIN(attempts,8))) + ABS(random()%1000),last_error=? WHERE profile=? AND state='pending' AND due<=? AND lease<=?",params![now,safe_code(code),profile,now,now]).map_err(error)?;
        Ok(())
    }

    pub fn pending_notification_reads(&self, scope: &Scope) -> Result<Vec<i64>, String> {
        let mut query = self.db.prepare("SELECT payload FROM events WHERE profile=? AND server=? AND epoch=? AND state='pending'").map_err(error)?;
        let rows = query
            .query_map(
                params![scope.profile_id, scope.server_id, scope.data_epoch],
                |row| row.get::<_, String>(0),
            )
            .map_err(error)?;
        let mut ids = Vec::new();
        for row in rows {
            if let Ok(BackgroundPayload::NotificationRead { notification_id }) =
                serde_json::from_str(&row.map_err(error)?)
            {
                ids.push(notification_id);
            }
        }
        Ok(ids)
    }

    pub fn retry_failed(&self, scope: &Scope) -> Result<(), String> {
        self.db.execute("UPDATE events SET state='pending',attempts=0,due=0,lease=0,last_error=NULL WHERE profile=? AND server=? AND epoch=? AND state='failed'", params![scope.profile_id,scope.server_id,scope.data_epoch]).map_err(error)?;
        Ok(())
    }

    pub fn streams(&self, scope: &Scope) -> Result<Vec<StreamStatus>, String> {
        let mut statement = self.db.prepare("SELECT stream,MAX(json_extract(payload,'$.connection_id')),MAX(json_extract(payload,'$.plugin_target')),SUM(state='pending'),SUM(state='failed'),MIN(occurred),MAX(attempts),MIN(CASE WHEN state='pending' THEN due END),MAX(last_error) FROM events WHERE profile=? AND server=? AND epoch=? GROUP BY stream ORDER BY SUM(state='failed') DESC,MIN(occurred) LIMIT 100").map_err(error)?;
        let rows = statement
            .query_map(
                params![scope.profile_id, scope.server_id, scope.data_epoch],
                |r| {
                    Ok(StreamStatus {
                        stream: r.get(0)?,
                        connection_id: r.get(1)?,
                        plugin_target: r.get(2)?,
                        pending: r.get(3)?,
                        failed: r.get(4)?,
                        oldest_at_ms: r.get(5)?,
                        attempts: r.get(6)?,
                        next_retry_at_ms: r.get(7)?,
                        last_error: r.get(8)?,
                    })
                },
            )
            .map_err(error)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(error)?;
        Ok(rows)
    }

    pub fn recover_stream(
        &self,
        scope: &Scope,
        stream: &str,
        discard: bool,
        now: i64,
    ) -> Result<(), String> {
        if !valid_key(stream) {
            return Err("Invalid background stream".into());
        }
        if discard {
            self.db.execute("DELETE FROM events WHERE profile=? AND server=? AND epoch=? AND stream=? AND lease<=?", params![scope.profile_id,scope.server_id,scope.data_epoch,stream,now]).map_err(error)?;
        } else {
            self.db.execute("UPDATE events SET state='pending',attempts=0,due=0,last_error=NULL WHERE profile=? AND server=? AND epoch=? AND stream=? AND state='failed' AND lease<=?", params![scope.profile_id,scope.server_id,scope.data_epoch,stream,now]).map_err(error)?;
        }
        // Preserve sequence metadata: removing work must never reset a destination watermark.
        Ok(())
    }
}

fn safe_code(code: &str) -> &str {
    if valid_key(code) {
        code
    } else {
        "delivery_failed"
    }
}

fn matches_stored_event(
    db: &Connection,
    batch: &DeliveryBatch,
    event: &BackgroundEvent,
) -> Result<bool, String> {
    let payload =
        serde_json::to_string(&event.payload).map_err(|_| "Invalid background payload")?;
    db.query_row("SELECT EXISTS(SELECT 1 FROM events e JOIN metadata m ON m.key='producer:' || e.profile WHERE e.id=? AND e.server=? AND e.epoch=? AND e.stream=? AND e.sequence=? AND e.occurred=? AND e.payload=? AND m.value=?)", params![event.event_id,batch.server_id,batch.data_epoch,event.stream,event.sequence,event.occurred_at_ms,payload,batch.producer_id], |row| row.get(0)).map_err(error)
}

fn retry_row(
    db: &Connection,
    id: &str,
    now: i64,
    code: &str,
    retry_after: Option<i64>,
) -> Result<(), String> {
    let attempts: i64 = db
        .query_row("SELECT attempts FROM events WHERE id=?", [id], |r| r.get(0))
        .optional()
        .map_err(error)?
        .unwrap_or(0);
    let delay = (1000_i64 * (1 << attempts.min(8))).min(300_000);
    let jitter = (uuid::Uuid::new_v4().as_u128() % (delay as u128 / 4 + 1)) as i64;
    let delay = (delay + jitter).max(retry_after.unwrap_or(0).clamp(0, 86_400_000));
    db.execute(
        "UPDATE events SET attempts=attempts+1,due=?,lease=0,last_error=? WHERE id=?",
        params![now + delay, safe_code(code), id],
    )
    .map_err(error)?;
    Ok(())
}
