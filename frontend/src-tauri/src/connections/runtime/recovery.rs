//! Recover only the service owned by the active desktop connection.

use super::*;
use std::time::{Duration, Instant};
use tauri::Emitter;

#[derive(Default)]
pub(super) struct RecoverySchedule {
    attempts: u32,
    healthy_since: Option<Instant>,
    next_attempt: Option<Instant>,
}

impl RecoverySchedule {
    fn due(&mut self, now: Instant, alive: bool) -> bool {
        if alive {
            let since = self.healthy_since.get_or_insert(now);
            if now.duration_since(*since) >= Duration::from_secs(60) {
                self.attempts = 0;
            }
            self.next_attempt = None;
            return false;
        }
        self.healthy_since = None;
        let delay = if self.attempts >= 3 {
            60
        } else {
            1 << (self.attempts + 1)
        };
        let deadline = self
            .next_attempt
            .get_or_insert(now + Duration::from_secs(delay));
        if now < *deadline {
            return false;
        }
        self.attempts = if self.attempts >= 3 {
            1
        } else {
            self.attempts + 1
        };
        self.next_attempt = None;
        true
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoveredConnection {
    profile_id: String,
    previous_pid: u32,
    local_service_pid: u32,
}

impl ConnectionRuntime {
    async fn recover_owned_service(&self) -> Result<Option<RecoveredConnection>, String> {
        let _operation = self.operation.lock().await;
        if self.shutting_down.load(Ordering::Acquire) {
            return Ok(None);
        }
        let (previous, response, generation) = {
            let mut active = self
                .active
                .lock()
                .map_err(|_| "Connection state unavailable")?;
            let Some(active) = active.as_mut() else {
                return Ok(None);
            };
            let Some(service) = active.service.as_mut() else {
                return Ok(None);
            };
            let alive = service.running()?;
            if !active.recovery.due(Instant::now(), alive) {
                return Ok(None);
            }
            let service = active.service.take().ok_or("Owned service disappeared")?;
            (
                service,
                active.response.clone(),
                self.generation.load(Ordering::Acquire),
            )
        };
        let previous_pid = previous.pid();
        let (previous, replacement) = tokio::task::spawn_blocking(move || {
            let replacement = previous.restart();
            (previous, replacement)
        })
        .await
        .map_err(|_| "Local service recovery task failed")?;
        let replacement = match replacement {
            Ok(service) => {
                let info = async {
                    CenterClient::local(&service.base_url)?
                        .info(&service.session_token)
                        .await
                }
                .await;
                match info {
                    Ok(info) if info.server_id == response.server_id => Ok((service, info)),
                    Ok(_) => Err("Recovered service identity changed".to_owned()),
                    Err(error) => Err(error),
                }
            }
            Err(error) => Err(error),
        };
        let mut active = self
            .active
            .lock()
            .map_err(|_| "Connection state unavailable")?;
        if self.shutting_down.load(Ordering::Acquire) || !self.is_current(generation) {
            return Ok(None);
        }
        let Some(active) = active.as_mut() else {
            return Ok(None);
        };
        match replacement {
            Ok((service, info)) => {
                let event = RecoveredConnection {
                    profile_id: response.profile_id,
                    previous_pid,
                    local_service_pid: service.pid(),
                };
                active.response.base_url = service.base_url.clone();
                active.response.session_token = service.session_token.clone();
                active.response.local_service_pid = Some(service.pid());
                active.response.data_epoch = info.maintenance.data_epoch;
                active.response.content_epoch = info.maintenance.content_epoch;
                active.service = Some(service);
                self.generation.fetch_add(1, Ordering::AcqRel);
                Ok(Some(event))
            }
            Err(error) => {
                active.service = Some(previous);
                Err(error)
            }
        }
    }
}

pub fn start_monitor(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(1)).await;
            let state = app.state::<ConnectionRuntime>();
            if state.shutting_down.load(Ordering::Acquire) {
                break;
            }
            match state.recover_owned_service().await {
                Ok(Some(event)) => {
                    log::info!("Owned local service recovered");
                    if let Err(error) = app.emit("magi-service-recovered", event) {
                        log::warn!("Could not notify the desktop about service recovery: {error}");
                    }
                }
                Ok(None) => {}
                Err(error) => log::warn!("Owned local service recovery failed: {error}"),
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recovery_backs_off_cools_down_and_resets_after_health() {
        let mut schedule = RecoverySchedule::default();
        let mut now = Instant::now();
        for delay in [2, 4, 8, 60] {
            assert!(!schedule.due(now, false));
            assert!(!schedule.due(now + Duration::from_secs(delay - 1), false));
            now += Duration::from_secs(delay);
            assert!(schedule.due(now, false));
        }
        assert!(!schedule.due(now, true));
        now += Duration::from_secs(60);
        assert!(!schedule.due(now, true));
        assert_eq!(schedule.attempts, 0);
    }

    #[tokio::test]
    async fn empty_remote_and_stopping_connections_never_launch_services() {
        let state = ConnectionRuntime::default();
        assert!(state.recover_owned_service().await.unwrap().is_none());
        *state.active.lock().unwrap() = Some(ActiveConnection {
            service: None,
            response: super::super::tests::connection_info("remote"),
            recovery: Default::default(),
        });
        assert!(state.recover_owned_service().await.unwrap().is_none());
        state.shutdown().unwrap();
        assert!(state.recover_owned_service().await.unwrap().is_none());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn crashed_owned_process_recovers_and_quit_cancels_inflight_recovery() {
        use std::os::unix::fs::PermissionsExt;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        for quit in [false, true] {
            let root = std::env::temp_dir().join(format!("magi-recovery-{}", uuid::Uuid::new_v4()));
            fs::create_dir_all(&root).unwrap();
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let base = format!("http://{}/api", listener.local_addr().unwrap());
            let binary = root.join("service");
            fs::write(&binary, format!("#!/bin/sh\nread bootstrap\nprintf '{{\"baseUrl\":\"{base}\",\"serverPid\":%s}}\\n' \"$$\"\nwhile IFS= read -r line; do :; done\n")).unwrap();
            fs::set_permissions(&binary, fs::Permissions::from_mode(0o700)).unwrap();
            let config = ServerConfig::for_development(&root, root.join("data"));
            let service = service_host::LocalService::start(
                &binary,
                &config,
                &root.join("config.json"),
                root.join("service.log"),
            )
            .unwrap();
            let original_pid = service.pid();
            let original_token = service.session_token.clone();
            let state = ConnectionRuntime::default();
            let mut response = super::super::tests::connection_info("local");
            response.base_url = base;
            response.local_service_pid = Some(original_pid);
            response.session_token = original_token.clone();
            *state.active.lock().unwrap() = Some(ActiveConnection {
                service: Some(service),
                response,
                recovery: Default::default(),
            });
            assert!(std::process::Command::new("/bin/kill")
                .args(["-KILL", &original_pid.to_string()])
                .status()
                .unwrap()
                .success());
            {
                let mut active = state.active.lock().unwrap();
                let active = active.as_mut().unwrap();
                while active.service.as_mut().unwrap().running().unwrap() {
                    std::thread::sleep(Duration::from_millis(5));
                }
                active.recovery.next_attempt = Some(Instant::now());
            }
            let generation = state.generation.load(Ordering::Acquire);
            let serve = async {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut request = [0; 4096];
                let _ = socket.read(&mut request).await.unwrap();
                if quit {
                    state.shutdown().unwrap();
                }
                let body = serde_json::json!({"success":true,"data":{"server_id":"center","protocol_version":2,"service_ready":true,"maintenance":{"data_epoch":"data","content_epoch":"content","phase":"idle"}}}).to_string();
                socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            };
            let (result, ()) = tokio::time::timeout(Duration::from_secs(10), async {
                tokio::join!(state.recover_owned_service(), serve)
            })
            .await
            .unwrap();
            if quit {
                assert!(result.unwrap().is_none());
                assert!(state.snapshot().is_err());
            } else {
                let event = result.unwrap().unwrap();
                assert_eq!(event.previous_pid, original_pid);
                assert_ne!(event.local_service_pid, original_pid);
                let (_, info) = state.snapshot().unwrap();
                assert_ne!(info.session_token, original_token);
                assert!(!state.is_current(generation));
                state.shutdown().unwrap();
                assert!(state.recover_owned_service().await.unwrap().is_none());
            }
            fs::remove_dir_all(root).unwrap();
        }
    }
}
