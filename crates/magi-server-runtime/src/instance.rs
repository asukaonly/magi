use std::fs::{File, OpenOptions};
use std::path::Path;

/// OS-backed lease. The persistent lock file must never be unlinked on exit.
pub struct InstanceLease {
    _file: File,
}

impl InstanceLease {
    pub fn acquire(path: &Path) -> Result<Self, String> {
        let mut options = OpenOptions::new();
        options.create(true).read(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
        }
        let file = options
            .open(path)
            .map_err(|e| format!("Failed to open instance lease: {e}"))?;
        let metadata = file
            .metadata()
            .map_err(|e| format!("Failed to inspect instance lease: {e}"))?;
        if !metadata.is_file() {
            return Err("Instance lease must be a regular file".into());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.nlink() != 1 || metadata.uid() != unsafe { libc::geteuid() } {
                return Err(
                    "Instance lease must be owned exclusively by the current account".into(),
                );
            }
        }
        file.try_lock()
            .map_err(|e| format!("Magi instance is already running or cannot be locked: {e}"))?;
        Ok(Self { _file: file })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lease_excludes_second_owner_and_survives_stale_file() {
        let path = std::env::temp_dir().join(format!("magi-lease-test-{}", std::process::id()));
        let first = InstanceLease::acquire(&path).unwrap();
        assert!(InstanceLease::acquire(&path).is_err());
        drop(first);
        assert!(path.exists());
        drop(InstanceLease::acquire(&path).unwrap());
        std::fs::remove_file(path).unwrap();
    }
}
