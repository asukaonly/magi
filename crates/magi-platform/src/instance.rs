use std::fs::{File, OpenOptions};
use std::path::Path;

/// OS-backed lease. The persistent lock file must never be unlinked on exit.
pub struct InstanceLease {
    _file: File,
}

impl InstanceLease {
    /// Inspect an existing lease without creating runtime directories or lock files.
    pub fn is_held(path: &Path) -> Result<bool, String> {
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
        }
        let file = match options.open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(error) => return Err(format!("Cannot inspect runtime lease: {error}")),
        };
        if !file.metadata().map_err(|e| e.to_string())?.is_file() {
            return Err("Runtime lease is not a regular file".into());
        }
        match file.try_lock() {
            Ok(()) => Ok(false),
            Err(std::fs::TryLockError::WouldBlock) => Ok(true),
            Err(std::fs::TryLockError::Error(error)) => Err(error.to_string()),
        }
    }

    /// Reserve one data root across service restarts, including cooldown periods.
    pub fn runtime_owner(root: &Path) -> Result<Self, String> {
        crate::private_data::protect_magi_data_root(root)?;
        let runtime = root.join("runtime");
        std::fs::create_dir_all(&runtime).map_err(|e| e.to_string())?;
        crate::private_data::protect_magi_data_root(&runtime)?;
        Self::acquire(&runtime.join("owner.lock"))
    }

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
        assert!(!InstanceLease::is_held(&path).unwrap());
        assert!(!path.exists());
        let first = InstanceLease::acquire(&path).unwrap();
        assert!(InstanceLease::is_held(&path).unwrap());
        assert!(InstanceLease::acquire(&path).is_err());
        drop(first);
        assert!(path.exists());
        assert!(!InstanceLease::is_held(&path).unwrap());
        drop(InstanceLease::acquire(&path).unwrap());
        std::fs::remove_file(path).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn lease_inspection_rejects_symlinks() {
        let root = std::env::temp_dir().join(format!("magi-lease-link-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let target = root.join("target");
        std::fs::write(&target, "unchanged").unwrap();
        std::os::unix::fs::symlink(&target, root.join("lock")).unwrap();
        assert!(InstanceLease::is_held(&root.join("lock")).is_err());
        assert_eq!(std::fs::read_to_string(target).unwrap(), "unchanged");
        std::fs::remove_dir_all(root).unwrap();
    }
}
