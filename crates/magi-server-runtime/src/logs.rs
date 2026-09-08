//! Bounded native output logs. File handles belong to the service, not children.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

const MAX_FILE_BYTES: u64 = 8 * 1024 * 1024;
const BACKUPS: usize = 2;

pub struct RotatingLog {
    path: PathBuf,
    file: Option<File>,
    limit: u64,
}

impl RotatingLog {
    pub fn open(path: &Path) -> io::Result<Self> {
        Self::with_limit(path, MAX_FILE_BYTES)
    }

    fn with_limit(path: &Path, limit: u64) -> io::Result<Self> {
        let file = open_private(path)?;
        let log = Self {
            path: path.to_owned(),
            file: Some(file),
            limit,
        };
        if log.file.as_ref().unwrap().metadata()?.len() > limit {
            // Retain a bounded tail when adopting an older, unbounded log.
            use std::io::{Read, Seek, SeekFrom};
            let mut old = open_private(path)?;
            old.seek(SeekFrom::End(-(limit as i64)))?;
            let mut tail = Vec::with_capacity(limit as usize);
            old.read_to_end(&mut tail)?;
            old.set_len(0)?;
            old.write_all(&tail)?;
        }
        for index in 1..=BACKUPS {
            let backup = log.backup(index);
            match fs::symlink_metadata(&backup) {
                Ok(metadata) if metadata.is_file() => {
                    if metadata.len() > limit {
                        fs::remove_file(backup)?;
                    }
                }
                Ok(_) => return Err(io::Error::other("Unexpected log backup entry")),
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
        }
        Ok(log)
    }

    fn backup(&self, index: usize) -> PathBuf {
        let mut name = self.path.as_os_str().to_os_string();
        name.push(format!(".{index}"));
        PathBuf::from(name)
    }

    fn rotate(&mut self) -> io::Result<()> {
        self.file.take();
        for index in (1..=BACKUPS).rev() {
            let destination = self.backup(index);
            match fs::symlink_metadata(&destination) {
                Ok(metadata) if metadata.is_file() => fs::remove_file(&destination)?,
                Ok(_) => return Err(io::Error::other("Unexpected log backup entry")),
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
            let source = if index == 1 {
                self.path.clone()
            } else {
                self.backup(index - 1)
            };
            match fs::symlink_metadata(&source) {
                Ok(metadata) if metadata.is_file() => fs::rename(source, destination)?,
                Ok(_) => return Err(io::Error::other("Unexpected log entry")),
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
        }
        self.file = Some(open_private(&self.path)?);
        Ok(())
    }
}

impl Write for RotatingLog {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.file.is_none() {
            self.file = Some(open_private(&self.path)?);
        }
        let length = self.file.as_ref().unwrap().metadata()?.len();
        if length >= self.limit {
            self.rotate()?;
        }
        let file = self.file.as_mut().unwrap();
        let available = self.limit.saturating_sub(file.metadata()?.len()) as usize;
        let count = bytes.len().min(available);
        file.write(&bytes[..count])
    }

    fn flush(&mut self) -> io::Result<()> {
        if let Some(file) = self.file.as_mut() {
            file.flush()?;
        }
        Ok(())
    }
}

fn open_private(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.create(true).read(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    let file = options.open(path)?;
    if !file.metadata()?.is_file() {
        return Err(io::Error::other("Log path is not a regular file"));
    }
    Ok(file)
}

pub(crate) fn capture_worker_output(
    stdout: tokio::process::ChildStdout,
    stderr: tokio::process::ChildStderr,
    log: RotatingLog,
) -> Vec<tokio::task::JoinHandle<()>> {
    let log = std::sync::Arc::new(std::sync::Mutex::new(log));
    vec![capture_pipe(stdout, log.clone()), capture_pipe(stderr, log)]
}

fn capture_pipe<R>(
    mut pipe: R,
    log: std::sync::Arc<std::sync::Mutex<RotatingLog>>,
) -> tokio::task::JoinHandle<()>
where
    R: tokio::io::AsyncRead + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        use tokio::io::AsyncReadExt;
        let mut bytes = [0u8; 8192];
        let mut warned = false;
        while let Ok(count) = pipe.read(&mut bytes).await {
            if count == 0 {
                break;
            }
            let result = log
                .lock()
                .map_err(|_| io::Error::other("Output log lock failed"))
                .and_then(|mut log| log.write_all(&bytes[..count]));
            if result.is_err() && !warned {
                eprintln!("Python output log is unavailable; output will continue to drain");
                warned = true;
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotation_keeps_a_bounded_tail_and_respects_external_clear() {
        let root = std::env::temp_dir().join(format!("magi-log-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let path = root.join("backend.log");
        let mut log = RotatingLog::with_limit(&path, 4).unwrap();
        log.write_all(b"abcdefghijklmnop").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"mnop");
        assert_eq!(fs::read(log.backup(1)).unwrap(), b"ijkl");
        assert_eq!(fs::read(log.backup(2)).unwrap(), b"efgh");
        OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&path)
            .unwrap();
        log.write_all(b"new").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"new");
        drop(log);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn adoption_bounds_existing_files_before_new_output() {
        let root = std::env::temp_dir().join(format!("magi-log-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let path = root.join("backend.log");
        fs::write(&path, b"old-long-output").unwrap();
        let log = RotatingLog::with_limit(&path, 4).unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"tput");
        drop(log);
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn symlink_outputs_and_backups_are_rejected() {
        use std::os::unix::fs::symlink;
        let root = std::env::temp_dir().join(format!("magi-log-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let target = root.join("protected");
        fs::write(&target, b"preserved").unwrap();
        let path = root.join("backend.log");
        symlink(&target, &path).unwrap();
        assert!(RotatingLog::with_limit(&path, 4).is_err());
        fs::remove_file(&path).unwrap();
        symlink(&target, root.join("backend.log.1")).unwrap();
        assert!(RotatingLog::with_limit(&path, 4).is_err());
        assert_eq!(fs::read(target).unwrap(), b"preserved");
        fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn output_keeps_draining_after_a_rotation_failure() {
        use tokio::io::AsyncWriteExt;
        let root = std::env::temp_dir().join(format!("magi-log-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let path = root.join("backend.log");
        let log = RotatingLog::with_limit(&path, 4).unwrap();
        // A filesystem failure must not leave the worker blocked on a full pipe.
        fs::create_dir(root.join("backend.log.1")).unwrap();
        let (mut writer, reader) = tokio::io::duplex(16);
        let capture = capture_pipe(reader, std::sync::Arc::new(std::sync::Mutex::new(log)));
        tokio::time::timeout(std::time::Duration::from_secs(3), async {
            writer.write_all(&vec![b'x'; 4096]).await.unwrap();
            drop(writer);
            capture.await.unwrap();
        })
        .await
        .unwrap();
        assert!(fs::metadata(&path).unwrap().len() <= 4);
        fs::remove_dir_all(root).unwrap();
    }
}
