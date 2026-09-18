//! Bounded, read-only log inspection with optional live following.

use clap::ValueEnum;
use magi_service_contract::config::ServerConfig;
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
    time::Duration,
};

#[derive(Clone, Copy, ValueEnum)]
pub enum Source {
    Service,
    Backend,
}

impl Source {
    pub fn filename(self) -> &'static str {
        match self {
            Self::Service => "service.log",
            Self::Backend => "backend.log",
        }
    }
}

fn open(path: &Path) -> Result<Option<File>, String> {
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    match options.open(path) {
        Ok(file) if file.metadata().map_err(|e| e.to_string())?.is_file() => Ok(Some(file)),
        Ok(_) => Err("Log must be a regular file".into()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("Cannot read {}: {error}", path.display())),
    }
}

fn read(file: &mut File, offset: u64) -> Result<Vec<u8>, String> {
    file.seek(SeekFrom::Start(offset))
        .map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    file.take(32 * 1024)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    Ok(bytes)
}

fn printable(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes)
        .chars()
        .filter(|c| !c.is_control() || matches!(*c, '\n' | '\t'))
        .collect()
}

pub fn tail(path: &Path, lines: usize) -> Result<String, String> {
    let Some(mut file) = open(path)? else {
        return Ok(String::new());
    };
    let size = file.metadata().map_err(|e| e.to_string())?.len();
    let text = printable(&read(&mut file, size.saturating_sub(32 * 1024))?);
    Ok(text
        .lines()
        .rev()
        .take(lines)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect::<Vec<_>>()
        .join("\n"))
}

pub fn run(
    config: &ServerConfig,
    source: Source,
    lines: usize,
    follow: bool,
) -> Result<(), String> {
    let path = config.data_dir.join("logs").join(source.filename());
    if !follow {
        let text = tail(&path, lines)?;
        println!(
            "{}",
            if text.is_empty() {
                "No log entries yet."
            } else {
                &text
            }
        );
        return Ok(());
    }
    eprintln!(
        "Following {}; Ctrl+C ends log viewing. Service state is unchanged.",
        path.display()
    );
    let mut previous = None;
    let mut offset = 0;
    loop {
        if let Some(mut file) = open(&path)? {
            let metadata = file.metadata().map_err(|e| e.to_string())?;
            #[cfg(unix)]
            let identity = {
                use std::os::unix::fs::MetadataExt;
                (metadata.dev(), metadata.ino())
            };
            #[cfg(not(unix))]
            let identity = metadata.created().ok();
            let reset = previous.as_ref() != Some(&identity) || metadata.len() < offset;
            if reset {
                offset = metadata.len().saturating_sub(32 * 1024);
            }
            let bytes = read(&mut file, offset)?;
            offset += bytes.len() as u64;
            let text = printable(&bytes);
            if reset {
                let tail = text
                    .lines()
                    .rev()
                    .take(lines)
                    .collect::<Vec<_>>()
                    .into_iter()
                    .rev()
                    .collect::<Vec<_>>()
                    .join("\n");
                if !tail.is_empty() {
                    println!("{tail}");
                }
            } else {
                print!("{text}");
            }
            std::io::stdout().flush().map_err(|e| e.to_string())?;
            previous = Some(identity);
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}
