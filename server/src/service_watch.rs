//! Foreground and launchd owner of the independent gateway process.

use magi_platform::instance::InstanceLease;
use magi_service_contract::{
    config::ServerConfig, health::ServiceHealth, restart_budget::RestartBudget, OwnerBootstrap,
    StartedServer, SERVER_PROTOCOL_VERSION,
};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::watch;

struct Service {
    child: Child,
    owner: Option<ChildStdin>,
    token: String,
}

impl Service {
    async fn start(
        config_path: &Path,
        deadline: Duration,
    ) -> Result<(Self, StartedServer), String> {
        let mut command = Command::new(std::env::current_exe().map_err(|e| e.to_string())?);
        command
            .args(["run", "--config"])
            .arg(config_path)
            .arg("--bootstrap-stdin")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);
        #[cfg(windows)]
        command.creation_flags(0x08000000);
        let child = command
            .spawn()
            .map_err(|e| format!("Could not launch service: {e}"))?;
        let mut service = Self {
            child,
            owner: None,
            token: format!(
                "{}{}",
                uuid::Uuid::new_v4().simple(),
                uuid::Uuid::new_v4().simple()
            ),
        };
        service.owner = service.child.stdin.take();
        let output = service
            .child
            .stdout
            .take()
            .ok_or("Service output is unavailable")?;
        let bootstrap = serde_json::to_string(&OwnerBootstrap {
            session_token: service.token.clone(),
        })
        .map_err(|e| e.to_string())?;
        service
            .owner
            .as_mut()
            .ok_or("Service owner pipe is unavailable")?
            .write_all(format!("{bootstrap}\n").as_bytes())
            .await
            .map_err(|e| e.to_string())?;
        let mut line = String::new();
        tokio::time::timeout(
            deadline,
            BufReader::new(output).take(4097).read_line(&mut line),
        )
        .await
        .map_err(|_| "Service listener startup timed out")?
        .map_err(|e| e.to_string())?;
        if line.len() > 4096 {
            return Err("Service listener report exceeds size limit".into());
        }
        let started: StartedServer =
            serde_json::from_str(&line).map_err(|_| "Invalid service listener report")?;
        let url = reqwest::Url::parse(&started.base_url)
            .map_err(|_| "Invalid service listener address")?;
        if service.child.id() != Some(started.server_pid)
            || url.scheme() != "http"
            || url.host_str() != Some("127.0.0.1")
            || url.port().is_none()
            || url.path() != "/api"
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            return Err("Service listener identity does not match its owner".into());
        }
        Ok((service, started))
    }

    async fn stop(&mut self, graceful: Option<Duration>) {
        self.owner.take();
        if let Some(deadline) = graceful {
            if matches!(
                tokio::time::timeout(deadline, self.child.wait()).await,
                Ok(Ok(_))
            ) {
                return;
            }
        }
        let _ = self.child.kill().await;
        let _ = self.child.wait().await;
    }
}

async fn stopped(shutdown: &mut watch::Receiver<bool>) {
    if !*shutdown.borrow() {
        let _ = shutdown.changed().await;
    }
}

async fn service_identity(
    http: &reqwest::Client,
    base: &str,
    token: &str,
) -> Result<String, String> {
    let mut response = http
        .get(format!("{base}/server/info"))
        .header("x-magi-session-token", token)
        .send()
        .await
        .map_err(|_| "Service responsiveness probe failed")?
        .error_for_status()
        .map_err(|_| "Service responsiveness probe was rejected")?;
    let mut body = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "Service probe response was interrupted")?
    {
        if body.len() + chunk.len() > 65536 {
            return Err("Service probe response exceeds size limit".into());
        }
        body.extend_from_slice(&chunk);
    }
    decode_service_identity(&body)
}

fn decode_service_identity(body: &[u8]) -> Result<String, String> {
    let value: serde_json::Value =
        serde_json::from_slice(body).map_err(|_| "Invalid service probe response")?;
    if value["success"] != true || value["data"]["protocol_version"] != SERVER_PROTOCOL_VERSION {
        return Err("Service probe contract is invalid".into());
    }
    let id = value["data"]["server_id"]
        .as_str()
        .ok_or("Service identity is missing")?;
    uuid::Uuid::parse_str(id).map_err(|_| "Service identity is invalid")?;
    // Management responsiveness is independent of model and maintenance readiness.
    Ok(id.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_accepts_unready_maintenance_but_rejects_invalid_identity() {
        let identity = uuid::Uuid::new_v4().to_string();
        let mut value = serde_json::json!({"success":true,"data":{
            "server_id":identity,"protocol_version":SERVER_PROTOCOL_VERSION,
            "service_ready":false,"maintenance":{"phase":"running"}
        }});
        assert_eq!(
            decode_service_identity(&serde_json::to_vec(&value).unwrap()).unwrap(),
            identity
        );
        value["data"]["server_id"] = "invalid".into();
        assert!(decode_service_identity(&serde_json::to_vec(&value).unwrap()).is_err());
        value["data"]["server_id"] = identity.into();
        value["data"]["protocol_version"] = 0.into();
        assert!(decode_service_identity(&serde_json::to_vec(&value).unwrap()).is_err());
    }
}

pub async fn run(
    config: ServerConfig,
    path: PathBuf,
    mut shutdown: watch::Receiver<bool>,
) -> Result<(), String> {
    let _lease = InstanceLease::runtime_owner(&config.data_dir)?;
    // Refuse a live service before entering retry policy, including direct owners.
    drop(InstanceLease::acquire(
        &config.data_dir.join("runtime/server.lock"),
    )?);
    let policy = &config.supervision;
    // Workspace feature unification can enable TLS through the desktop client.
    let _ = rustls::crypto::ring::default_provider().install_default();
    let http = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(policy.probe_timeout_secs))
        .build()
        .map_err(|e| e.to_string())?;
    let mut expected_id = None;
    let mut budget = RestartBudget::default();
    loop {
        let launch = tokio::select! {
            biased;
            _ = stopped(&mut shutdown) => return Ok(()),
            result = Service::start(&path, Duration::from_secs(config.shutdown_timeout_secs + 15)) => result,
        };
        match launch {
            Ok((mut service, started)) => {
                if let Ok(json) = serde_json::to_string(&started) {
                    let _ = writeln!(std::io::stdout(), "{json}");
                }
                let mut health = ServiceHealth::default();
                loop {
                    if *shutdown.borrow() {
                        service
                            .stop(Some(Duration::from_secs(
                                config.owner_shutdown_timeout_secs(),
                            )))
                            .await;
                        return Ok(());
                    }
                    if let Some(status) = service.child.try_wait().map_err(|e| e.to_string())? {
                        eprintln!("Owned service exited: {status}");
                        break;
                    }
                    if health.due(Instant::now(), policy) {
                        let result = tokio::select! {
                            biased;
                            _ = stopped(&mut shutdown) => continue,
                            result = service_identity(&http, &started.base_url, &service.token) => result,
                        };
                        let responsive = match result {
                            Ok(id)
                                if expected_id.as_ref().is_none_or(|expected| *expected == id) =>
                            {
                                expected_id = Some(id);
                                true
                            }
                            _ => false,
                        };
                        health.record(responsive);
                        if responsive {
                            budget.healthy(
                                Instant::now(),
                                Duration::from_secs(policy.stable_after_secs),
                            );
                        } else {
                            budget.interrupted();
                        }
                        if health.failed(policy) {
                            eprintln!("Owned service is unresponsive; terminating its process before recovery");
                            service.stop(None).await;
                            break;
                        }
                    }
                    tokio::select! {
                        _ = stopped(&mut shutdown) => {},
                        _ = tokio::time::sleep(Duration::from_millis(100)) => {},
                    }
                }
            }
            Err(error) => eprintln!("Owned service startup failed: {error}"),
        }
        budget.interrupted();
        if config.max_restarts == 0 {
            eprintln!("Service recovery is disabled; restart the owner explicitly");
            stopped(&mut shutdown).await;
            return Ok(());
        }
        let delay = if budget.attempts >= config.max_restarts {
            budget.reset();
            policy.cooldown_secs
        } else {
            budget.attempts += 1;
            1 << budget.attempts.min(4)
        };
        eprintln!("Owned service recovery will retry in {delay} seconds");
        tokio::select! {
            _ = stopped(&mut shutdown) => return Ok(()),
            _ = tokio::time::sleep(Duration::from_secs(delay)) => {},
        }
    }
}
