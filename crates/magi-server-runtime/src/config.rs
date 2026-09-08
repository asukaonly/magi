use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServerConfig {
    pub data_dir: PathBuf,
    #[serde(default = "default_port")]
    pub port: u16,
    pub worker: WorkerLaunch,
    pub builtin_avatar_dir: Option<PathBuf>,
    #[serde(default = "default_restarts")]
    pub max_restarts: u32,
    #[serde(default = "default_startup_timeout")]
    pub startup_timeout_secs: u64,
    #[serde(default = "default_shutdown_timeout")]
    pub shutdown_timeout_secs: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerLaunch {
    pub executable: PathBuf,
    #[serde(default)]
    pub args: Vec<String>,
    pub working_directory: Option<PathBuf>,
    #[serde(default)]
    pub python_path: Vec<PathBuf>,
    pub plugin_python: PathBuf,
}

fn default_port() -> u16 {
    19080
}
fn default_restarts() -> u32 {
    3
}
fn default_startup_timeout() -> u64 {
    120
}
fn default_shutdown_timeout() -> u64 {
    10
}

impl ServerConfig {
    pub fn load(path: &Path) -> Result<Self, String> {
        let bytes =
            std::fs::read(path).map_err(|e| format!("Failed to read server configuration: {e}"))?;
        if bytes.len() > 64 * 1024 {
            return Err("Server configuration exceeds 64 KiB".into());
        }
        let config: Self = serde_json::from_slice(&bytes)
            .map_err(|e| format!("Invalid server configuration: {e}"))?;
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<(), String> {
        validate_absolute(&self.data_dir)?;
        let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE"));
        if self.data_dir.parent().is_none()
            || home
                .as_ref()
                .is_some_and(|h| self.data_dir == PathBuf::from(h))
        {
            return Err("Server data directory must be dedicated to Magi".into());
        }
        validate_absolute(&self.worker.executable)?;
        validate_absolute(&self.worker.plugin_python)?;
        for path in self
            .worker
            .python_path
            .iter()
            .chain(self.worker.working_directory.iter())
            .chain(self.builtin_avatar_dir.iter())
        {
            validate_absolute(path)?;
        }
        if self.max_restarts > 10
            || !(1..=600).contains(&self.startup_timeout_secs)
            || !(1..=60).contains(&self.shutdown_timeout_secs)
        {
            return Err("Server restart or timeout limits are out of range".into());
        }
        Ok(())
    }

    pub fn for_development(project: &Path, data_dir: PathBuf) -> Self {
        let python = project.join(if cfg!(windows) {
            ".venv/Scripts/python.exe"
        } else {
            ".venv/bin/python"
        });
        Self {
            data_dir,
            port: default_port(),
            max_restarts: default_restarts(),
            startup_timeout_secs: default_startup_timeout(),
            shutdown_timeout_secs: default_shutdown_timeout(),
            builtin_avatar_dir: Some(project.join("backend/personalities/avatar")),
            worker: WorkerLaunch {
                executable: python.clone(),
                plugin_python: python,
                args: vec![project
                    .join("backend/run_server.py")
                    .to_string_lossy()
                    .into_owned()],
                working_directory: Some(project.join("backend")),
                python_path: vec![project.join("backend/src"), project.join("sdk/src")],
            },
        }
    }
}

fn validate_absolute(path: &Path) -> Result<(), String> {
    if !path.is_absolute() || path.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err("Server paths must be absolute and must not contain parent traversal".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configuration_rejects_ambiguous_paths_and_unbounded_restarts() {
        let project = std::env::current_dir().unwrap();
        let mut config = ServerConfig::for_development(&project, project.join("test-data"));
        assert!(config.validate().is_ok());
        config.data_dir = PathBuf::from("relative");
        assert!(config.validate().is_err());
        config.data_dir = project.join("../data");
        assert!(config.validate().is_err());
        config.data_dir = project.join("test-data");
        config.max_restarts = 100;
        assert!(config.validate().is_err());
    }
}
