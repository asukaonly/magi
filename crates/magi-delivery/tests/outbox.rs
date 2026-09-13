use magi_delivery::{DeliveryPolicy, Outbox, Scope};
use magi_service_contract::delivery::*;

fn id() -> String {
    uuid::Uuid::new_v4().to_string()
}
fn scope() -> Scope {
    Scope {
        profile_id: "local".into(),
        server_id: id(),
        data_epoch: id(),
    }
}
fn payload(value: u32) -> BackgroundPayload {
    BackgroundPayload::PluginEvent {
        plugin_target: "test".into(),
        event_type: "observation".into(),
        data: serde_json::json!({"value":value}),
    }
}
fn ack(batch: &DeliveryBatch, status: ReceiptStatus) -> DeliveryReceipt {
    DeliveryReceipt {
        server_id: batch.server_id.clone(),
        data_epoch: batch.data_epoch.clone(),
        receipts: batch
            .events
            .iter()
            .map(|e| EventReceipt {
                event_id: e.event_id.clone(),
                status: status.clone(),
                code: "test".into(),
            })
            .collect(),
    }
}

#[test]
fn restart_replays_same_identity_and_sequence_until_ack() {
    let dir = tempfile::tempdir().unwrap();
    let scope = scope();
    let event_id = id();
    let mut queue = Outbox::open(dir.path()).unwrap();
    assert!(Outbox::open(dir.path()).is_err());
    queue
        .enqueue(
            &scope,
            "photos",
            &event_id,
            payload(1),
            DeliveryPolicy::Reliable,
            1,
        )
        .unwrap();
    let first = queue.claim(&scope, 1).unwrap();
    drop(queue); // The network response was lost after the receiver committed.
    let mut queue = Outbox::open(dir.path()).unwrap();
    let replay = queue.claim(&scope, 2).unwrap();
    assert_eq!(
        serde_json::to_value(&first).unwrap(),
        serde_json::to_value(&replay).unwrap()
    );
    queue
        .acknowledge(&replay, &ack(&replay, ReceiptStatus::Accepted), 2)
        .unwrap();
    assert_eq!(queue.status(&scope).unwrap().pending, 0);
    queue
        .enqueue(
            &scope,
            "photos",
            &id(),
            payload(2),
            DeliveryPolicy::Reliable,
            3,
        )
        .unwrap();
    assert_eq!(queue.claim(&scope, 3).unwrap().events[0].sequence, 2);
}

#[test]
fn failures_block_only_their_stream_and_manual_retry_recovers() {
    let dir = tempfile::tempdir().unwrap();
    let scope = scope();
    let mut q = Outbox::open(dir.path()).unwrap();
    for (stream, value) in [("photos", 1), ("photos", 2), ("music", 3)] {
        q.enqueue(
            &scope,
            stream,
            &id(),
            payload(value),
            DeliveryPolicy::Reliable,
            value.into(),
        )
        .unwrap();
    }
    let first = q.claim(&scope, 10).unwrap();
    assert_eq!(first.events.len(), 2);
    let mut receipt = ack(&first, ReceiptStatus::Accepted);
    receipt
        .receipts
        .iter_mut()
        .find(|r| {
            first
                .events
                .iter()
                .any(|e| e.event_id == r.event_id && e.stream == "photos")
        })
        .unwrap()
        .status = ReceiptStatus::Rejected;
    q.acknowledge(&first, &receipt, 10).unwrap();
    assert!(q.claim(&scope, 100000).unwrap().events.is_empty());
    assert_eq!(q.status(&scope).unwrap().failed, 1);
    q.retry_failed(&scope).unwrap();
    let retry = q.claim(&scope, 100001).unwrap();
    assert_eq!(retry.events[0].sequence, 1);
    q.acknowledge(&retry, &ack(&retry, ReceiptStatus::Accepted), 100001)
        .unwrap();
    assert_eq!(q.claim(&scope, 100002).unwrap().events[0].sequence, 2);
}

#[test]
fn latest_never_replaces_in_flight_content_and_best_effort_expires() {
    let dir = tempfile::tempdir().unwrap();
    let scope = scope();
    let mut q = Outbox::open(dir.path()).unwrap();
    q.enqueue(
        &scope,
        "state",
        &id(),
        payload(1),
        DeliveryPolicy::Latest,
        1,
    )
    .unwrap();
    q.enqueue(
        &scope,
        "state",
        &id(),
        payload(2),
        DeliveryPolicy::Latest,
        2,
    )
    .unwrap();
    let in_flight = q.claim(&scope, 3).unwrap();
    assert_eq!(in_flight.events[0].payload, payload(2));
    q.enqueue(
        &scope,
        "state",
        &id(),
        payload(3),
        DeliveryPolicy::Latest,
        4,
    )
    .unwrap();
    q.enqueue(
        &scope,
        "state",
        &id(),
        payload(4),
        DeliveryPolicy::Latest,
        5,
    )
    .unwrap();
    assert_eq!(q.status(&scope).unwrap().pending, 2);
    q.acknowledge(&in_flight, &ack(&in_flight, ReceiptStatus::Accepted), 6)
        .unwrap();
    let next = q.claim(&scope, 7).unwrap();
    assert_eq!(next.events[0].payload, payload(4));
    q.acknowledge(&next, &ack(&next, ReceiptStatus::Accepted), 8)
        .unwrap();
    q.enqueue(
        &scope,
        "metrics",
        &id(),
        payload(1),
        DeliveryPolicy::BestEffort,
        9,
    )
    .unwrap();
    assert!(q.claim(&scope, 3_600_010).unwrap().events.is_empty());
}

#[test]
fn scopes_epochs_and_receipts_cannot_cross_destinations() {
    let dir = tempfile::tempdir().unwrap();
    let one = scope();
    let mut two = scope();
    two.profile_id = "other".into();
    let mut q = Outbox::open(dir.path()).unwrap();
    q.enqueue(
        &one,
        "photos",
        &id(),
        payload(1),
        DeliveryPolicy::Reliable,
        1,
    )
    .unwrap();
    q.enqueue(
        &two,
        "photos",
        &id(),
        payload(2),
        DeliveryPolicy::Reliable,
        2,
    )
    .unwrap();
    let first = q.claim(&one, 3).unwrap();
    let mut bad = ack(&first, ReceiptStatus::Accepted);
    bad.server_id = two.server_id.clone();
    assert!(q.acknowledge(&first, &bad, 4).is_err());
    assert_eq!(q.status(&one).unwrap().pending, 1);
    q.retire_epochs(&one.profile_id, &one.server_id, &id())
        .unwrap();
    assert_eq!(q.status(&one).unwrap().pending, 0);
    assert_eq!(q.status(&two).unwrap().pending, 1);
    // A late ACK from the old center cannot remove new-center work.
    q.acknowledge(&first, &ack(&first, ReceiptStatus::Accepted), 5)
        .unwrap();
    assert_eq!(q.status(&two).unwrap().pending, 1);
    q.forget(&two.profile_id).unwrap();
    assert_eq!(q.status(&two).unwrap().pending, 0);
}

#[test]
fn retry_deadlines_survive_restart_and_respect_server_backpressure() {
    let dir = tempfile::tempdir().unwrap();
    let scope = scope();
    let mut q = Outbox::open(dir.path()).unwrap();
    q.enqueue(
        &scope,
        "facts",
        &id(),
        payload(1),
        DeliveryPolicy::Reliable,
        1,
    )
    .unwrap();
    let batch = q.claim(&scope, 2).unwrap();
    q.retry(&batch, 3, "server_busy", Some(60_000)).unwrap();
    drop(q);
    let mut q = Outbox::open(dir.path()).unwrap();
    assert!(q.claim(&scope, 60_002).unwrap().events.is_empty());
    assert_eq!(q.claim(&scope, 60_003).unwrap().events.len(), 1);
}

#[test]
fn duplicate_center_profiles_have_independent_producers_and_stale_acks_cannot_delete_reused_ids() {
    let dir = tempfile::tempdir().unwrap();
    let one = scope();
    let mut two = one.clone();
    two.profile_id = "second".into();
    let mut q = Outbox::open(dir.path()).unwrap();
    let event_id = id();
    q.enqueue(
        &one,
        "facts",
        &event_id,
        payload(1),
        DeliveryPolicy::Reliable,
        1,
    )
    .unwrap();
    let old = q.claim(&one, 2).unwrap();
    q.forget(&one.profile_id).unwrap();
    q.enqueue(
        &two,
        "facts",
        &event_id,
        payload(2),
        DeliveryPolicy::Reliable,
        3,
    )
    .unwrap();
    let new = q.claim(&two, 4).unwrap();
    assert_ne!(old.producer_id, new.producer_id);
    q.acknowledge(&old, &ack(&old, ReceiptStatus::Accepted), 5)
        .unwrap();
    assert_eq!(q.status(&two).unwrap().pending, 1);
    q.acknowledge(&new, &ack(&new, ReceiptStatus::Accepted), 5)
        .unwrap();
    assert_eq!(q.status(&two).unwrap().pending, 0);
}

#[test]
fn a_newer_storage_schema_is_rejected_without_mutation() {
    let dir = tempfile::tempdir().unwrap();
    let db = rusqlite::Connection::open(dir.path().join("outbox.db")).unwrap();
    db.execute_batch("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); INSERT INTO metadata VALUES ('version','99')").unwrap();
    assert!(Outbox::open(dir.path()).is_err());
    let tables: i64 = db
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(tables, 1);
}

#[test]
fn invalid_and_oversized_content_never_enters_storage() {
    let dir = tempfile::tempdir().unwrap();
    let scope = scope();
    let mut q = Outbox::open(dir.path()).unwrap();
    let event = id();
    q.enqueue(
        &scope,
        "facts",
        &event,
        payload(1),
        DeliveryPolicy::Reliable,
        1,
    )
    .unwrap();
    assert!(q
        .enqueue(
            &scope,
            "facts",
            &event,
            payload(2),
            DeliveryPolicy::Reliable,
            1
        )
        .is_err());
    let large = BackgroundPayload::PluginEvent {
        plugin_target: "test".into(),
        event_type: "facts".into(),
        data: serde_json::json!({"text":"a".repeat(MAX_EVENT_BYTES)}),
    };
    assert!(q
        .enqueue(&scope, "facts", &id(), large, DeliveryPolicy::Reliable, 1)
        .is_err());
    assert_eq!(q.status(&scope).unwrap().pending, 1);
}

#[test]
fn full_queue_rejects_reliable_work_and_drops_best_effort_explicitly() {
    let dir = tempfile::tempdir().unwrap();
    let scope = scope();
    let mut q = Outbox::open(dir.path()).unwrap();
    q.enqueue(
        &scope,
        "facts",
        &id(),
        payload(1),
        DeliveryPolicy::Reliable,
        1,
    )
    .unwrap();
    let db = rusqlite::Connection::open(dir.path().join("outbox.db")).unwrap();
    db.execute("UPDATE events SET bytes=64*1024*1024", [])
        .unwrap();
    assert!(q
        .enqueue(
            &scope,
            "facts",
            &id(),
            payload(2),
            DeliveryPolicy::Reliable,
            2
        )
        .is_err());
    assert!(!q
        .enqueue(
            &scope,
            "metrics",
            &id(),
            payload(3),
            DeliveryPolicy::BestEffort,
            3
        )
        .unwrap());
    assert_eq!(q.status(&scope).unwrap().pending, 1);
}

#[cfg(unix)]
#[test]
fn storage_is_private_and_forgetting_erases_payload() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let scope = scope();
    let mut q = Outbox::open(dir.path()).unwrap();
    let payload = BackgroundPayload::PluginEvent {
        plugin_target: "test".into(),
        event_type: "facts".into(),
        data: serde_json::json!({"text":"private-test-fact-fragment"}),
    };
    q.enqueue(&scope, "facts", &id(), payload, DeliveryPolicy::Reliable, 1)
        .unwrap();
    assert_eq!(
        std::fs::metadata(dir.path().join("outbox.db"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    q.forget(&scope.profile_id).unwrap();
    let needle = b"private-test-fact-fragment";
    assert!(!std::fs::read(dir.path().join("outbox.db"))
        .unwrap()
        .windows(needle.len())
        .any(|s| s == needle));
}
