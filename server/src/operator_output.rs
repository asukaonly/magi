//! One output policy for people at a terminal and programs reading stdout.

use clap::Args;
use serde::Serialize;
use std::io::IsTerminal;

#[derive(Args, Clone, Copy, Default)]
pub struct Options {
    /// Print structured JSON instead of terminal summaries.
    #[arg(long, global = true, conflicts_with = "text")]
    pub json: bool,
    /// Print readable text even when stdout is redirected.
    #[arg(long, global = true)]
    pub text: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Text,
    Json,
}

impl Options {
    pub fn format(self) -> Format {
        self.resolve(std::io::stdout().is_terminal())
    }

    fn resolve(self, terminal: bool) -> Format {
        if self.json || (!self.text && !terminal) {
            Format::Json
        } else {
            Format::Text
        }
    }
}

impl Format {
    pub fn print(
        self,
        value: &impl Serialize,
        readable: impl FnOnce() -> Result<String, String>,
    ) -> Result<(), String> {
        match self {
            Self::Json => println!(
                "{}",
                serde_json::to_string_pretty(value).map_err(|e| e.to_string())?
            ),
            Self::Text => println!("{}", clean(&readable()?)),
        }
        Ok(())
    }

    pub fn progress(self) -> bool {
        self == Self::Text && std::io::stderr().is_terminal()
    }
}

#[derive(Clone, Copy)]
pub enum Tone {
    Success,
    Pending,
    Warning,
    Info,
    Error,
}

impl Tone {
    pub fn line(self, text: impl AsRef<str>) -> String {
        let icons = (std::io::stdout().is_terminal() || std::io::stderr().is_terminal())
            && std::env::var("TERM").as_deref() != Ok("dumb");
        let mark = match (self, icons) {
            (Self::Success, true) => "✅",
            (Self::Pending, true) => "⏳",
            (Self::Warning, true) => "⚠️",
            (Self::Info, true) => "ℹ️",
            (Self::Error, true) => "❌",
            (Self::Success, false) => "[OK]",
            (Self::Pending, false) => "[WAIT]",
            (Self::Warning, false) => "[WARN]",
            (Self::Info, false) => "[INFO]",
            (Self::Error, false) => "[ERROR]",
        };
        format!("{mark} {}", clean(text.as_ref()))
    }
}

pub fn clean(text: &str) -> String {
    text.chars()
        .filter(|c| !c.is_control() || *c == '\n')
        .collect()
}

pub fn next_step(path: &std::path::Path, label: &str, args: &[&str]) -> String {
    format!(
        "\n\nNext step — {label}\n  {}",
        crate::operator_command::display(path, args)
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn output_selection_is_explicit_or_follows_stdout() {
        assert!(Options::default().resolve(true) == Format::Text);
        assert!(Options::default().resolve(false) == Format::Json);
        assert!(
            Options {
                json: true,
                text: false
            }
            .resolve(true)
                == Format::Json
        );
        assert!(
            Options {
                json: false,
                text: true
            }
            .resolve(false)
                == Format::Text
        );
    }
}
