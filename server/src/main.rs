use std::io::{BufRead, Read, Write};
use std::path::PathBuf;
use std::sync::Arc;

use magi_gateway::api::security::GatewaySecurity;
use magi_server_runtime::{config::ServerConfig, supervisor};
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DesktopBootstrap {
    session_token: String,
}

fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn execute() -> Result<(), String> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.is_empty() || args.iter().any(|a| a == "--help" || a == "-h") {
        println!("Magi Server\n\n  run --config <file> [--bootstrap-stdin]\n  init --config <file> --data-dir <directory> --development-root <repository>\n\nServer HTTP listens on loopback. Remote HTTPS is provided by a same-machine proxy.");
        return Ok(());
    }
    let command = &args[0];
    let config_path = required_option(&args[1..], "--config")?;
    match command.as_str() {
        "init" => {
            reject_unknown_options(
                &args[1..],
                &["--config", "--data-dir", "--development-root"],
                &[],
            )?;
            let data_dir = PathBuf::from(required_option(&args[1..], "--data-dir")?);
            let project = PathBuf::from(required_option(&args[1..], "--development-root")?);
            let config = ServerConfig::for_development(&project, data_dir);
            config.validate()?;
            let bytes = serde_json::to_vec_pretty(&config).map_err(|e| e.to_string())?;
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&config_path)
                .map_err(|e| format!("Failed to create server configuration: {e}"))?;
            file.write_all(&bytes).map_err(|e| e.to_string())?;
            println!("Created server configuration: {config_path}");
            Ok(())
        }
        "run" => {
            reject_unknown_options(&args[1..], &["--config"], &["--bootstrap-stdin"])?;
            let config = ServerConfig::load(&PathBuf::from(config_path))?;
            // Resolve process-wide runtime paths before creating any runtime threads.
            std::env::set_var("MAGI_HOME", &config.data_dir);
            let desktop = args.iter().any(|a| a == "--bootstrap-stdin");
            let token = if desktop {
                let mut line = String::new();
                std::io::stdin()
                    .lock()
                    .take(8193)
                    .read_line(&mut line)
                    .map_err(|e| e.to_string())?;
                if line.len() > 8192 {
                    return Err("Desktop bootstrap exceeds size limit".into());
                }
                let bootstrap: DesktopBootstrap =
                    serde_json::from_str(&line).map_err(|_| "Invalid desktop bootstrap")?;
                if bootstrap.session_token.len() < 32 {
                    return Err("Desktop bootstrap credential is too short".into());
                }
                bootstrap.session_token
            } else {
                // Remote authorization is owned by the service authentication layer.
                magi_gateway::api::security::generate_session_token()
            };
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .map_err(|e| e.to_string())?;
            runtime.block_on(async move {
                let (shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);
                if desktop {
                    let parent_lost = shutdown_tx.clone();
                    std::thread::spawn(move || {
                        let mut byte = [0u8; 1];
                        let _ = std::io::stdin().read(&mut byte);
                        parent_lost.send_replace(true);
                    });
                }
                tokio::spawn(async move {
                    #[cfg(unix)]
                    {
                        match tokio::signal::unix::signal(
                            tokio::signal::unix::SignalKind::terminate(),
                        ) {
                            Ok(mut terminate) => {
                                tokio::select! {
                                    _ = tokio::signal::ctrl_c() => {},
                                    _ = terminate.recv() => {},
                                }
                            }
                            Err(_) => {
                                let _ = tokio::signal::ctrl_c().await;
                            }
                        }
                    }
                    #[cfg(not(unix))]
                    {
                        let _ = tokio::signal::ctrl_c().await;
                    }
                    shutdown_tx.send_replace(true);
                });
                let (started_tx, started_rx) = tokio::sync::oneshot::channel();
                tokio::spawn(async move {
                    if let Ok(info) = started_rx.await {
                        if let Ok(json) = serde_json::to_string(&info) {
                            println!("{json}");
                            let _ = std::io::stdout().flush();
                        }
                    }
                });
                supervisor::run(
                    config,
                    Arc::new(GatewaySecurity::new(token)),
                    shutdown_rx,
                    started_tx,
                )
                .await
            })
        }
        _ => Err("Unknown server command; use --help".into()),
    }
}

fn required_option(args: &[String], name: &str) -> Result<String, String> {
    let positions = args
        .iter()
        .enumerate()
        .filter(|(_, a)| a.as_str() == name)
        .map(|(i, _)| i)
        .collect::<Vec<_>>();
    if positions.len() != 1 {
        return Err(format!("Specify {name} exactly once"));
    }
    args.get(positions[0] + 1)
        .filter(|value| !value.starts_with("--"))
        .cloned()
        .ok_or_else(|| format!("{name} requires a value"))
}

fn reject_unknown_options(args: &[String], options: &[&str], flags: &[&str]) -> Result<(), String> {
    let mut i = 0;
    while i < args.len() {
        if options.contains(&args[i].as_str()) {
            i += 2;
        } else if flags.contains(&args[i].as_str()) {
            i += 1;
        } else {
            return Err(format!("Unknown server option: {}", args[i]));
        }
    }
    Ok(())
}
