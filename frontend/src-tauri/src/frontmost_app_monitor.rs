use rusqlite::{params, Connection};
use serde_json::json;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

const SOURCE_KIND_DESKTOP: &str = "desktop";
const PRODUCER_FRONTMOST_APP_MONITOR: &str = "frontmost_app_monitor";
const PLUGIN_TARGET_SCREEN_TIME: &str = "screen_time";
const EVENT_TYPE_FRONTMOST_APP_ACTIVATED: &str = "frontmost_app_activated";

static MONITOR_INSTALLED: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Debug, PartialEq, Eq)]
struct PluginIngressEvent {
    source_kind: String,
    producer: String,
    plugin_target: String,
    event_type: String,
    occurred_at_ms: i64,
    payload_json: String,
    cursor_key: Option<String>,
}

impl PluginIngressEvent {
    fn frontmost_app_activated(
        occurred_at_ms: i64,
        bundle_id: &str,
        app_name: &str,
    ) -> Result<Self, String> {
        let payload_json = serde_json::to_string(&json!({
            "bundle_id": bundle_id,
            "app_name": app_name,
        }))
        .map_err(|err| format!("Failed to encode frontmost-app payload JSON: {err}"))?;

        Ok(Self {
            source_kind: SOURCE_KIND_DESKTOP.to_string(),
            producer: PRODUCER_FRONTMOST_APP_MONITOR.to_string(),
            plugin_target: PLUGIN_TARGET_SCREEN_TIME.to_string(),
            event_type: EVENT_TYPE_FRONTMOST_APP_ACTIVATED.to_string(),
            occurred_at_ms,
            payload_json,
            cursor_key: None,
        })
    }
}

#[derive(Clone, Debug)]
struct PluginIngressEventStore {
    db_path: PathBuf,
}

impl PluginIngressEventStore {
    fn new(db_path: PathBuf) -> Result<Self, String> {
        let parent_dir = db_path.parent().ok_or_else(|| {
            format!(
                "Plugin ingress database path has no parent: {}",
                db_path.display()
            )
        })?;
        fs::create_dir_all(parent_dir).map_err(|err| {
            format!(
                "Failed to create plugin ingress database directory {}: {err}",
                parent_dir.display()
            )
        })?;

        let store = Self { db_path };
        store.initialize_schema()?;
        Ok(store)
    }

    fn open_connection(&self) -> Result<Connection, String> {
        Connection::open(&self.db_path).map_err(|err| {
            format!(
                "Failed to open plugin ingress database {}: {err}",
                self.db_path.display()
            )
        })
    }

    fn initialize_schema(&self) -> Result<(), String> {
        let connection = self.open_connection()?;
        connection
            .execute_batch(
                r#"
                CREATE TABLE IF NOT EXISTS plugin_ingress_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_kind TEXT NOT NULL,
                    producer TEXT NOT NULL,
                    plugin_target TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at_ms INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    cursor_key TEXT,
                    status TEXT NOT NULL,
                    claimed_by TEXT,
                    claimed_at_ms INTEGER,
                    processed_at_ms INTEGER,
                    last_error TEXT,
                    created_at_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plugin_ingress_events_status_created
                    ON plugin_ingress_events(status, created_at_ms ASC, event_id ASC);
                CREATE INDEX IF NOT EXISTS idx_plugin_ingress_events_target_type_status
                    ON plugin_ingress_events(plugin_target, event_type, status, created_at_ms ASC, event_id ASC);
                "#,
            )
            .map_err(|err| format!("Failed to initialize plugin ingress schema: {err}"))?;
        Ok(())
    }

    fn append_event(&self, event: &PluginIngressEvent) -> Result<(), String> {
        let connection = self.open_connection()?;
        connection
            .execute(
                r#"
                INSERT INTO plugin_ingress_events (
                    source_kind,
                    producer,
                    plugin_target,
                    event_type,
                    occurred_at_ms,
                    payload_json,
                    cursor_key,
                    status,
                    claimed_by,
                    claimed_at_ms,
                    processed_at_ms,
                    last_error,
                    created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, NULL, ?)
                "#,
                params![
                    event.source_kind,
                    event.producer,
                    event.plugin_target,
                    event.event_type,
                    event.occurred_at_ms,
                    event.payload_json,
                    event.cursor_key,
                    current_time_millis(),
                ],
            )
            .map_err(|err| format!("Failed to append plugin ingress event: {err}"))?;
        Ok(())
    }
}

fn runtime_trace_db_path() -> Result<PathBuf, String> {
    let home_dir = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "HOME environment variable is not set".to_string())?;
    Ok(home_dir.join(".magi").join("data").join("runtime_trace.db"))
}

fn current_time_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or_default()
}

#[cfg(target_os = "macos")]
mod macos {
    use super::{
        current_time_millis, runtime_trace_db_path, PluginIngressEvent, PluginIngressEventStore,
    };
    use block2::RcBlock;
    use objc2::rc::Retained;
    use objc2::runtime::ProtocolObject;
    use objc2_app_kit::{
        NSRunningApplication, NSWorkspace, NSWorkspaceDidActivateApplicationNotification,
    };
    use objc2_foundation::{NSNotification, NSNotificationCenter, NSObjectProtocol};
    use std::ptr::NonNull;

    pub struct FrontmostAppMonitor {
        notification_center: Retained<NSNotificationCenter>,
        observer: Retained<ProtocolObject<dyn NSObjectProtocol>>,
        _callback: RcBlock<dyn Fn(NonNull<NSNotification>)>,
    }

    impl FrontmostAppMonitor {
        pub fn start() -> Result<Self, String> {
            let store = PluginIngressEventStore::new(runtime_trace_db_path()?)?;
            let workspace = NSWorkspace::sharedWorkspace();
            let notification_center = workspace.notificationCenter();
            let store_for_callback = store.clone();
            let callback = RcBlock::new(move |_notification: NonNull<NSNotification>| {
                if let Err(err) = capture_frontmost_app(&store_for_callback, current_time_millis())
                {
                    eprintln!("failed to append frontmost-app ingress event: {err}");
                }
            });

            let observer = unsafe {
                notification_center.addObserverForName_object_queue_usingBlock(
                    Some(NSWorkspaceDidActivateApplicationNotification),
                    None,
                    None,
                    &callback,
                )
            };

            capture_frontmost_app(&store, current_time_millis())?;

            Ok(Self {
                notification_center,
                observer,
                _callback: callback,
            })
        }
    }

    impl Drop for FrontmostAppMonitor {
        fn drop(&mut self) {
            unsafe {
                self.notification_center
                    .removeObserver(self.observer.as_ref());
            }
        }
    }

    fn capture_frontmost_app(
        store: &PluginIngressEventStore,
        occurred_at_ms: i64,
    ) -> Result<(), String> {
        let workspace = NSWorkspace::sharedWorkspace();
        let application = workspace
            .frontmostApplication()
            .ok_or_else(|| "Frontmost application is not available".to_string())?;

        let bundle_id = app_bundle_id(&application);
        if bundle_id.is_empty() {
            return Err("Frontmost application bundle ID is empty".to_string());
        }
        let app_name = app_name(&application);

        let event =
            PluginIngressEvent::frontmost_app_activated(occurred_at_ms, &bundle_id, &app_name)?;
        store.append_event(&event)
    }

    fn app_bundle_id(application: &NSRunningApplication) -> String {
        application
            .bundleIdentifier()
            .map(|value| value.to_string())
            .unwrap_or_default()
    }

    fn app_name(application: &NSRunningApplication) -> String {
        application
            .localizedName()
            .map(|value| value.to_string())
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| app_bundle_id(application))
    }
}

#[cfg(target_os = "macos")]
pub fn setup_monitor() -> Result<(), String> {
    if MONITOR_INSTALLED
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return Ok(());
    }

    match macos::FrontmostAppMonitor::start() {
        Ok(monitor) => {
            let _ = Box::leak(Box::new(monitor));
            Ok(())
        }
        Err(err) => {
            MONITOR_INSTALLED.store(false, Ordering::SeqCst);
            Err(err)
        }
    }
}

#[cfg(not(target_os = "macos"))]
pub fn setup_monitor() -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{PluginIngressEvent, PluginIngressEventStore};
    use rusqlite::Connection;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn plugin_ingress_store_initializes_schema_and_appends_events() {
        let db_path = temp_db_path("append");
        let store =
            PluginIngressEventStore::new(db_path.clone()).expect("expected store to initialize");
        let event = PluginIngressEvent::frontmost_app_activated(
            1_700_000_000_000,
            "com.apple.Safari",
            "Safari",
        )
        .expect("expected event payload");

        store
            .append_event(&event)
            .expect("expected append to succeed");

        let connection = Connection::open(&db_path).expect("expected test database to open");
        let row = connection
            .query_row(
                "SELECT source_kind, producer, plugin_target, event_type, occurred_at_ms, payload_json, status FROM plugin_ingress_events",
                [],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, i64>(4)?,
                        row.get::<_, String>(5)?,
                        row.get::<_, String>(6)?,
                    ))
                },
            )
            .expect("expected stored ingress row");

        assert_eq!(row.0, "desktop");
        assert_eq!(row.1, "frontmost_app_monitor");
        assert_eq!(row.2, "screen_time");
        assert_eq!(row.3, "frontmost_app_activated");
        assert_eq!(row.4, 1_700_000_000_000);
        assert_eq!(row.6, "pending");
        assert!(row.5.contains("\"bundle_id\":\"com.apple.Safari\""));

        cleanup_temp_db(&db_path);
    }

    #[test]
    fn frontmost_app_event_encodes_bundle_and_name_payload() {
        let event =
            PluginIngressEvent::frontmost_app_activated(123, "com.apple.Terminal", "Terminal")
                .expect("expected event payload");

        assert_eq!(event.source_kind, "desktop");
        assert_eq!(event.producer, "frontmost_app_monitor");
        assert_eq!(event.plugin_target, "screen_time");
        assert_eq!(event.event_type, "frontmost_app_activated");
        assert_eq!(
            event.payload_json,
            "{\"app_name\":\"Terminal\",\"bundle_id\":\"com.apple.Terminal\"}"
        );
    }

    fn temp_db_path(suffix: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("expected system time after epoch")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "magi-frontmost-app-monitor-{}-{}-{}.db",
            std::process::id(),
            suffix,
            unique
        ))
    }

    fn cleanup_temp_db(path: &Path) {
        let _ = std::fs::remove_file(path);
    }
}
