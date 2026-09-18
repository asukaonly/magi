//! Explicit automation commands and the interactive default entry point.

use clap::{Args, Parser, Subcommand};
use magi_service_contract::config::ServerConfig;
use std::{
    io::{IsTerminal, Write},
    path::{Path, PathBuf},
};

#[derive(Parser)]
#[command(name = "magi-server", version = version(), about = "Magi Server — run without a command to set up or manage this deployment")]
pub struct Cli {
    /// Deployment configuration (default: ~/.config/magi-server/server.json).
    #[arg(long, global = true)]
    pub config: Option<PathBuf>,
    #[command(flatten)]
    pub init: InitOptions,
    #[command(subcommand)]
    pub command: Option<Command>,
}

#[derive(Args, Default)]
pub struct InitOptions {
    /// Dedicated data directory, only when creating a deployment.
    #[arg(long, global = true)]
    pub data_dir: Option<PathBuf>,
    /// Loopback port, only for a new deployment (0 selects an available port).
    #[arg(long, global = true)]
    pub port: Option<u16>,
    /// Source checkout containing the development Python environment.
    #[arg(long, global = true, conflicts_with = "bundle_root")]
    pub development_root: Option<PathBuf>,
    /// Permanent directory containing the packaged server and Python runtime.
    #[arg(long, global = true)]
    pub bundle_root: Option<PathBuf>,
}

impl InitOptions {
    pub fn supplied(&self) -> bool {
        self.data_dir.is_some()
            || self.port.is_some()
            || self.development_root.is_some()
            || self.bundle_root.is_some()
    }
}

#[derive(Subcommand)]
pub enum Command {
    /// Create deployment configuration without prompts; does not start the service.
    Init,
    /// Run in the foreground without prompts. Ctrl+C stops the owned service.
    Run {
        #[arg(long, hide = true, conflicts_with = "shutdown_on_stdin_close")]
        bootstrap_stdin: bool,
        #[arg(long, hide = true)]
        shutdown_on_stdin_close: bool,
        #[arg(long)]
        log_file: Option<PathBuf>,
    },
    /// Configure language, models and persona on an already running service.
    Configure {
        /// Read a setup document from standard input instead of showing prompts.
        #[arg(long)]
        from_stdin: bool,
    },
    /// Read deployment settings or validate them without starting the service.
    Config {
        #[command(subcommand)]
        action: ConfigAction,
    },
    /// Inspect this deployment. Human-readable in a terminal; JSON when piped.
    Status {
        #[arg(long)]
        json: bool,
    },
    /// Read the latest service log lines without starting a service.
    Logs {
        #[arg(long, default_value_t = 40, value_parser = clap::value_parser!(u16).range(1..=200))]
        lines: u16,
        #[arg(long, value_enum, default_value = "service")]
        source: crate::operator_logs::Source,
        /// Keep displaying new lines until Ctrl+C; never starts a service.
        #[arg(long)]
        follow: bool,
    },
    /// Generate a single-use pairing code valid for 30 minutes.
    Pair,
    /// Guide a desktop connection, including HTTPS checks for another device.
    Connect,
    /// List plugin connections and their IDs for collector enrollment.
    CollectorConnections {
        #[arg(long)]
        plugin_id: String,
    },
    /// Return source collection to the center after revoking its collector.
    ReleaseCollector {
        #[arg(long)]
        connection_id: String,
        #[arg(long)]
        source_type: String,
    },
    /// Issue a scoped source collector grant; does not grant center management access.
    PairCollector {
        #[arg(long)]
        connection_id: String,
        #[arg(long)]
        source_type: String,
    },
    /// Run a device source without starting a center. Use `collect --help` for commands.
    #[command(disable_help_flag = true)]
    Collect {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
    /// List paired devices.
    Clients,
    /// Revoke a paired device.
    Revoke {
        #[arg(long)]
        client_id: String,
    },
    /// Install and start the current user's macOS login service.
    Install,
    /// Start the installed macOS login service.
    Start,
    /// Stop the installed macOS login service.
    Stop,
    /// Restart the installed macOS login service.
    Restart,
    /// Remove the macOS login service, preserving all data.
    Uninstall,
}

#[derive(Subcommand)]
pub enum ConfigAction {
    Show,
    Validate,
    /// Change run mode or port, and inspect deployment folders.
    Edit,
    /// Read-only current-deployment checks and upgrade instructions.
    UpgradeCheck,
}

fn version() -> &'static str {
    static VERSION: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    VERSION.get_or_init(|| {
        format!(
            "{} (protocol {})",
            env!("CARGO_PKG_VERSION"),
            magi_service_contract::SERVER_PROTOCOL_VERSION
        )
    })
}

pub fn home_path(relative: &str) -> Result<PathBuf, String> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(|home| PathBuf::from(home).join(relative))
        .ok_or("User home is unavailable".into())
}

pub fn load_config(path: &Path) -> Result<ServerConfig, String> {
    if !path.try_exists().map_err(|e| e.to_string())? {
        return Err(format!("No deployment configuration exists at {}. Run magi-server with the same --config path for guided setup, or use init for automation.", path.display()));
    }
    ServerConfig::load(path)
        .map_err(|error| format!("Cannot load deployment at {}: {error}", path.display()))
}

pub fn execute(
    cli: Cli,
    output: &mut Option<crate::managed_output::ManagedOutput>,
) -> Result<(), String> {
    let path = match cli.config {
        Some(path) => path,
        None => home_path(".config/magi-server/server.json")?,
    };
    if !path.is_absolute() {
        return Err("Server configuration path must be absolute".into());
    }
    if cli.command.is_some()
        && !matches!(cli.command, Some(Command::Init | Command::Collect { .. }))
        && cli.init.supplied()
    {
        return Err(
            "Deployment initialization options only apply to init or first-run setup".into(),
        );
    }
    match cli.command {
        None => crate::console::launch(&path, cli.init),
        Some(Command::Init) => {
            if path.try_exists().map_err(|e| e.to_string())? {
                return Err(format!("Deployment already exists at {}. Run magi-server with the same --config path to manage it, or configure to edit its running Magi settings.", path.display()));
            }
            let data = match &cli.init.data_dir {
                Some(data) => data.clone(),
                None => home_path(".magi-center")?,
            };
            create_config(&path, &cli.init, data, cli.init.port.unwrap_or(19080))?;
            println!("Created server configuration: {}", path.display());
            Ok(())
        }
        Some(Command::Run {
            bootstrap_stdin,
            shutdown_on_stdin_close,
            log_file,
        }) => crate::run(
            path,
            bootstrap_stdin,
            shutdown_on_stdin_close,
            log_file,
            output,
        ),
        Some(Command::Collect { args }) => run_collector(&cli.init, args),
        Some(Command::CollectorConnections { plugin_id }) => {
            if !magi_gateway_key(&plugin_id) {
                return Err("Invalid plugin identity".into());
            }
            let config = load_config(&path)?;
            crate::deployment_status::require_management(&config, &path, true)?;
            let api = crate::console_api::Api::connect(&config)?;
            print_json(&api.call("GET", &format!("/plugins/{plugin_id}/connections"), None)?)
        }
        Some(Command::ReleaseCollector {
            connection_id,
            source_type,
        }) => {
            if !magi_gateway_key(&connection_id) {
                return Err("Invalid connection identity".into());
            }
            let config = load_config(&path)?;
            crate::deployment_status::require_management(&config, &path, true)?;
            let api = crate::console_api::Api::connect(&config)?;
            print_json(&api.call(
                "POST",
                &format!("/delivery/collector/{connection_id}/release"),
                Some(&serde_json::json!({"source_type":source_type})),
            )?)
        }
        Some(Command::PairCollector {
            connection_id,
            source_type,
        }) => {
            let config = load_config(&path)?;
            crate::deployment_status::require_management(&config, &path, true)?;
            let api = crate::console_api::Api::connect(&config)?;
            print_json(&api.call(
                "POST",
                "/server/collector-grants",
                Some(&serde_json::json!({"connection_id":connection_id,"source_type":source_type})),
            )?)
        }
        Some(Command::Configure { from_stdin }) => crate::console::configure(&path, from_stdin),
        Some(Command::Connect) => {
            crate::console::terminal()?;
            let config = load_config(&path)?;
            crate::deployment_status::require_management(&config, &path, false)?;
            let api = crate::console_api::Api::connect(&config)?;
            crate::console_connection::guide(&config, &api.base_url)
        }
        Some(Command::Status { json }) => {
            let status = crate::deployment_status::inspect_path(&path)?;
            if json || !std::io::stdout().is_terminal() {
                print_json(&serde_json::to_value(status).map_err(|e| e.to_string())?)
            } else {
                println!("Deployment: {}\n{}", path.display(), status.describe());
                if status.configuration_available() {
                    let config = load_config(&path)?;
                    let api = crate::console_api::Api::connect(&config)?;
                    if !api.completed()? {
                        println!("Setup: incomplete. Run configure or connect to finish.");
                    } else if api.agent_ready()? {
                        println!("Setup: complete. Agent is ready.");
                    } else {
                        println!("Setup: complete. Agent is not ready; inspect logs.");
                    }
                }
                Ok(())
            }
        }
        Some(Command::Logs {
            lines,
            source,
            follow,
        }) => crate::operator_logs::run(&load_config(&path)?, source, usize::from(lines), follow),
        Some(Command::Config { action }) => {
            let config = load_config(&path)?;
            match action {
                ConfigAction::Show => {
                    print_json(&serde_json::to_value(config).map_err(|e| e.to_string())?)
                }
                ConfigAction::Validate => {
                    validate_worker(&config)?;
                    println!("Deployment configuration is valid.");
                    Ok(())
                }
                ConfigAction::Edit => {
                    crate::console::terminal()?;
                    let mut foreground = None;
                    crate::console_deployment::menu(&path, &mut foreground)?;
                    if let Some(child) = foreground {
                        println!("Running in foreground. Press Ctrl+C to stop this service.");
                        child.wait()?;
                    }
                    Ok(())
                }
                ConfigAction::UpgradeCheck => {
                    println!("{}", crate::console_deployment::upgrade_check(&path)?);
                    Ok(())
                }
            }
        }
        Some(command) => {
            use crate::console_api::Request;
            let request = match command {
                Command::Pair => Request::Pair,
                Command::Clients => Request::Clients,
                Command::Revoke { client_id } => Request::Revoke { client_id },
                Command::Install => {
                    return print_json(&crate::service_install::execute("install", &path)?)
                }
                Command::Start => {
                    return print_json(&crate::service_install::execute("start", &path)?)
                }
                Command::Stop => {
                    return print_json(&crate::service_install::execute("stop", &path)?)
                }
                Command::Restart => {
                    return print_json(&crate::service_install::execute("restart", &path)?)
                }
                Command::Uninstall => {
                    return print_json(&crate::service_install::execute("uninstall", &path)?)
                }
                _ => unreachable!(),
            };
            let config = load_config(&path)?;
            crate::deployment_status::require_management(&config, &path, false)?;
            print_json(&crate::console_api::management(&config, request)?)
        }
    }
}

pub fn print_json(value: &serde_json::Value) -> Result<(), String> {
    println!(
        "{}",
        serde_json::to_string_pretty(value).map_err(|e| e.to_string())?
    );
    Ok(())
}

pub fn validate_worker(config: &ServerConfig) -> Result<(), String> {
    config.validate()?;
    for path in [&config.worker.executable, &config.worker.plugin_python] {
        if !path.is_file() {
            return Err(format!("Runtime executable is missing: {}", path.display()));
        }
    }
    Ok(())
}

pub fn create_config(
    path: &Path,
    options: &InitOptions,
    data: PathBuf,
    port: u16,
) -> Result<ServerConfig, String> {
    let mut config = if let Some(project) = &options.development_root {
        ServerConfig::for_development(project, data)
    } else {
        let bundle = options.bundle_root.clone().unwrap_or(
            std::env::current_exe()
                .map_err(|e| e.to_string())?
                .parent()
                .ok_or("Service bundle directory is unavailable")?
                .to_owned(),
        );
        ServerConfig::for_bundle(&bundle, data)
    };
    config.port = port;
    validate_worker(&config)
        .map_err(|error| format!("{error}. Use --development-root for a source checkout."))?;
    create_private_file(
        path,
        &serde_json::to_vec_pretty(&config).map_err(|e| e.to_string())?,
    )?;
    Ok(config)
}

pub fn create_private_file(path: &Path, bytes: &[u8]) -> Result<(), String> {
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
        .open(path)
        .map_err(|e| format!("Cannot create {}: {e}", path.display()))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|e| e.to_string())
}

pub fn replace_private_file(path: &Path, bytes: &[u8]) -> Result<(), String> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.is_file() {
                return Err("Configuration must be a regular file, not a link".into());
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                if metadata.nlink() != 1 || metadata.uid() != unsafe { libc::geteuid() } {
                    return Err(
                        "Configuration must be owned exclusively by the current account".into(),
                    );
                }
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.to_string()),
    }
    let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4().simple()));
    let result = create_private_file(&temporary, bytes)
        .and_then(|_| std::fs::rename(&temporary, path).map_err(|e| e.to_string()));
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn run_collector(options: &InitOptions, args: Vec<String>) -> Result<(), String> {
    let data = options
        .data_dir
        .clone()
        .unwrap_or(home_path(".magi-collector")?);
    let config = if let Some(project) = &options.development_root {
        ServerConfig::for_development(project, data)
    } else {
        let bundle = options.bundle_root.clone().unwrap_or(
            std::env::current_exe()
                .map_err(|e| e.to_string())?
                .parent()
                .ok_or("Bundle directory is unavailable")?
                .to_owned(),
        );
        ServerConfig::for_bundle(&bundle, data)
    };
    validate_worker(&config)?;
    let mut command = std::process::Command::new(&config.worker.executable);
    command
        .args(&config.worker.args)
        .arg("--collector")
        .args(args)
        .env("MAGI_HOME", &config.data_dir)
        .env("MAGI_PLUGIN_PYTHON", &config.worker.plugin_python)
        .env_remove("MAGI_IPC_AUTH_TOKEN")
        .env_remove("MAGI_IPC_SOCKET")
        .env_remove("MAGI_SERVER_PARENT_PID")
        .env_remove("MAGI_DATA_EPOCH")
        .env_remove("MAGI_BACKEND_LOG_FILE");
    if let Some(cwd) = &config.worker.working_directory {
        command.current_dir(cwd);
    }
    if config.worker.python_path.is_empty() {
        command.env_remove("PYTHONPATH");
    } else {
        command.env(
            "PYTHONPATH",
            std::env::join_paths(&config.worker.python_path).map_err(|e| e.to_string())?,
        );
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        Err(format!("Collector could not start: {}", command.exec()))
    }
    #[cfg(not(unix))]
    {
        let status = command.status().map_err(|e| e.to_string())?;
        if status.success() {
            Ok(())
        } else {
            Err("Collector exited with an error".into())
        }
    }
}

fn magi_gateway_key(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
}
