//! Copyable commands retain the selected deployment and quote paths as shell arguments.

use std::path::{Path, PathBuf};

struct Context {
    executable: PathBuf,
    default_config: Option<PathBuf>,
}

impl Context {
    fn current() -> Option<Self> {
        if let Some(launcher) = std::env::var_os("MAGI_CLI_LAUNCHER") {
            Some(Self {
                executable: launcher.into(),
                default_config: crate::cli::home_path(".config/magi-server/dev.json").ok(),
            })
        } else {
            Some(Self {
                executable: std::env::current_exe().ok()?,
                default_config: crate::cli::home_path(".config/magi-server/server.json").ok(),
            })
        }
    }

    fn format(&self, config: &Path, args: &[&str]) -> Option<String> {
        let mut words = vec![quote(self.executable.to_str()?)?];
        for arg in args {
            words.push(quote(arg)?);
        }
        if self.default_config.as_deref() != Some(config) {
            words.push("--config".into());
            words.push(quote(config.to_str()?)?);
        }
        Some(words.join(" "))
    }
}

fn quote(value: &str) -> Option<String> {
    if value.chars().any(char::is_control) {
        return None;
    }
    if !value.is_empty()
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"/_-.".contains(&b))
    {
        Some(value.into())
    } else {
        Some(format!("'{}'", value.replace('\'', "'\\''")))
    }
}

pub fn display(config: &Path, args: &[&str]) -> String {
    Context::current().and_then(|context| context.format(config, args))
        .unwrap_or_else(|| "Command cannot be displayed for this path; use the original executable and configuration.".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn development_commands_use_the_launcher_and_preserve_custom_config() {
        let context = Context {
            executable: "./scripts/dev-server.sh".into(),
            default_config: Some("/user/dev.json".into()),
        };
        assert_eq!(
            context
                .format(Path::new("/user/dev.json"), &["stop"])
                .unwrap(),
            "./scripts/dev-server.sh stop"
        );
        assert_eq!(
            context
                .format(
                    Path::new("/user/custom config.json"),
                    &["status", "--details"]
                )
                .unwrap(),
            "./scripts/dev-server.sh status --details --config '/user/custom config.json'"
        );
    }

    #[cfg(unix)]
    #[test]
    fn command_paths_round_trip_through_shell_without_expansion() {
        let context = Context {
            executable: "/bundle/Magi's $(echo unsafe) `whoami`/server".into(),
            default_config: None,
        };
        let config = Path::new("/data/config's $HOME.json");
        let command = context.format(config, &["stop"]).unwrap();
        // Parse the displayed command as positional arguments; never execute its executable.
        let output = std::process::Command::new("/bin/sh")
            .args(["-c", &format!("set -- {command}\nprintf '%s\\0' \"$@\"")])
            .output()
            .unwrap();
        assert!(output.status.success());
        let args: Vec<_> = output
            .stdout
            .split(|b| *b == 0)
            .filter(|v| !v.is_empty())
            .collect();
        assert_eq!(
            args,
            vec![
                context.executable.to_str().unwrap().as_bytes(),
                b"stop",
                b"--config",
                config.to_str().unwrap().as_bytes()
            ]
        );
        assert!(context
            .format(Path::new("/config\nother.json"), &[])
            .is_none());
    }
}
