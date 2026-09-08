mod service_install;

use std::io::{BufRead, Read, Write};
use std::path::PathBuf;

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
    if args == ["--version"] {
        println!("Magi Server {} (protocol 1)", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    if args.is_empty() || args.iter().any(|a| a == "--help" || a == "-h") {
        println!("Magi Server\n\n  run --config <file> [--bootstrap-stdin]\n  status|pair|clients|revoke --config <file> [--client-id <id>]\n  init --config <file> --data-dir <directory> [--bundle-root <directory> | --development-root <repository>] [--port <port>]\n  install|start|stop|restart|uninstall --config <file> (macOS user service)\n\nServer HTTP listens on loopback. Remote HTTPS is provided by a same-machine proxy.");
        return Ok(());
    }
    let command = &args[0];
    let config_path = required_option(&args[1..], "--config")?;
    match command.as_str() {
        "init" => {
            reject_unknown_options(
                &args[1..],
                &[
                    "--config",
                    "--data-dir",
                    "--development-root",
                    "--bundle-root",
                    "--port",
                ],
                &[],
            )?;
            let data_dir = PathBuf::from(required_option(&args[1..], "--data-dir")?);
            let development = optional_option(&args[1..], "--development-root")?;
            let bundle = optional_option(&args[1..], "--bundle-root")?;
            if development.is_some() && bundle.is_some() {
                return Err("Choose either a service bundle or a development repository".into());
            }
            let mut config = if let Some(project) = development {
                ServerConfig::for_development(&PathBuf::from(project), data_dir)
            } else {
                let bundle = match bundle {
                    Some(path) => PathBuf::from(path),
                    None => std::env::current_exe()
                        .map_err(|e| e.to_string())?
                        .parent()
                        .ok_or("Service bundle directory is unavailable")?
                        .to_path_buf(),
                };
                if !bundle
                    .join(if cfg!(windows) {
                        "sidecar-dist/magi-backend.exe"
                    } else {
                        "sidecar-dist/magi-backend"
                    })
                    .is_file()
                {
                    return Err("Service bundle is incomplete; use --development-root for a source checkout".into());
                }
                ServerConfig::for_bundle(&bundle, data_dir)
            };
            if let Some(port) = optional_option(&args[1..], "--port")? {
                config.port = port
                    .parse::<u16>()
                    .map_err(|_| "Server port must be between 0 and 65535")?;
            }
            config.validate()?;
            let bytes = serde_json::to_vec_pretty(&config).map_err(|e| e.to_string())?;
            let path = PathBuf::from(&config_path);
            if !path.is_absolute() {
                return Err("Server configuration path must be absolute".into());
            }
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            let mut options = std::fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
            }
            let mut file = options
                .open(&config_path)
                .map_err(|e| format!("Failed to create server configuration: {e}"))?;
            file.write_all(&bytes)
                .and_then(|_| file.sync_all())
                .map_err(|e| e.to_string())?;
            println!("Created server configuration: {config_path}");
            Ok(())
        }
        "install" | "start" | "stop" | "restart" | "uninstall" => {
            reject_unknown_options(&args[1..], &["--config"], &[])?;
            service_install::execute(command, &PathBuf::from(config_path))
        }
        #[cfg(unix)]
        "status" | "pair" | "clients" | "revoke" => {
            reject_unknown_options(
                &args[1..],
                if command == "revoke" {
                    &["--config", "--client-id"]
                } else {
                    &["--config"]
                },
                &[],
            )?;
            let config = ServerConfig::load(&PathBuf::from(config_path))?;
            use magi_server_runtime::management::{request, Request};
            let request_kind = match command.as_str() {
                "pair" => Request::Pair,
                "clients" => Request::Clients,
                "revoke" => Request::Revoke {
                    client_id: required_option(&args[1..], "--client-id")?,
                },
                _ => Request::Status,
            };
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(|e| e.to_string())?;
            let result = runtime.block_on(request(&config.data_dir, request_kind))?;
            println!(
                "{}",
                serde_json::to_string_pretty(&result).map_err(|e| e.to_string())?
            );
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
                Some(bootstrap.session_token)
            } else {
                None
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
                supervisor::run(config, token, shutdown_rx, started_tx).await
            })
        }
        _ => Err("Unknown server command; use --help".into()),
    }
}

fn optional_option(args: &[String], name: &str) -> Result<Option<String>, String> {
    if args.iter().any(|arg| arg == name) {
        required_option(args, name).map(Some)
    } else {
        Ok(None)
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
