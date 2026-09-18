mod cli;
mod console;
mod console_api;
mod console_connection;
mod console_deployment;
mod console_manager;
mod console_runtime;
mod deployment_status;
mod managed_output;
mod operator_logs;
mod service_inspection;
mod service_install;
mod service_watch;

use clap::Parser;
use magi_server_runtime::supervisor;
use magi_service_contract::OwnerBootstrap;
use std::io::{BufRead, IsTerminal, Read, Write};
use std::path::PathBuf;

fn main() {
    let mut output = None;
    let args = cli::Cli::parse();
    let guided = std::io::stderr().is_terminal()
        && matches!(
            args.command,
            None | Some(
                cli::Command::Configure { from_stdin: false }
                    | cli::Command::Connect
                    | cli::Command::Config {
                        action: cli::ConfigAction::Edit
                    }
            )
        );
    let outcome = cli::execute(args, &mut output);
    let failed = outcome.is_err();
    if let Err(error) = outcome {
        if !guided || cliclack::outro_cancel(&error).is_err() {
            eprintln!("{error}");
        }
    }
    drop(output);
    if failed {
        std::process::exit(1);
    }
}

fn run(
    config_path: PathBuf,
    externally_owned: bool,
    shutdown_on_stdin_close: bool,
    log_file: Option<PathBuf>,
    output: &mut Option<managed_output::ManagedOutput>,
) -> Result<(), String> {
    if let Some(path) = log_file {
        *output = Some(
            managed_output::ManagedOutput::start(&path, !externally_owned)
                .map_err(|e| e.to_string())?,
        );
    }
    let config = cli::load_config(&config_path)?;
    // Resolve process-wide runtime paths before creating any runtime threads.
    std::env::set_var("MAGI_HOME", &config.data_dir);
    let token = if externally_owned {
        let mut line = String::new();
        std::io::stdin()
            .lock()
            .take(8193)
            .read_line(&mut line)
            .map_err(|e| e.to_string())?;
        if line.len() > 8192 {
            return Err("Owner bootstrap exceeds size limit".into());
        }
        let bootstrap: OwnerBootstrap =
            serde_json::from_str(&line).map_err(|_| "Invalid owner bootstrap")?;
        if bootstrap.session_token.len() < 32 {
            return Err("Owner bootstrap credential is too short".into());
        }
        Some(bootstrap.session_token)
    } else {
        None
    };
    let mut builder = if externally_owned {
        tokio::runtime::Builder::new_multi_thread()
    } else {
        tokio::runtime::Builder::new_current_thread()
    };
    let runtime = builder.enable_all().build().map_err(|e| e.to_string())?;
    runtime.block_on(async move {
        let (shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);
        if externally_owned || shutdown_on_stdin_close {
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
                match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
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
        if !externally_owned {
            return service_watch::run(config, config_path, shutdown_rx).await;
        }
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
