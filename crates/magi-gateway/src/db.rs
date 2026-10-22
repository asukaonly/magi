use std::path::{Path, PathBuf};
#[cfg(test)]
use std::sync::{Mutex, MutexGuard};
use std::sync::{OnceLock, RwLock};

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/// Resolve the Magi base directory (~/.magi).
pub fn magi_base_dir() -> PathBuf {
    if let Some(path) = magi_base_dir_override()
        .read()
        .ok()
        .and_then(|guard| guard.clone())
    {
        return path;
    }

    configured_magi_base_dir().expect("Invalid Magi data directory")
}

/// Resolve the process-wide directory shared with the desktop host and Python.
pub fn configured_magi_base_dir() -> Result<PathBuf, String> {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .map_err(|_| "Neither HOME nor USERPROFILE is set".to_string())?;
    resolve_magi_base_dir(std::env::var("MAGI_HOME").ok().as_deref(), &home)
}

fn resolve_magi_base_dir(override_path: Option<&str>, home: &Path) -> Result<PathBuf, String> {
    let Some(value) = override_path else {
        return Ok(home.join(".magi"));
    };
    let path = PathBuf::from(value);
    if value.is_empty()
        || !path.is_absolute()
        || path.parent().is_none()
        || path == home
        || path
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err("MAGI_HOME must name a dedicated absolute data directory".to_string());
    }
    Ok(path)
}

static MAGI_BASE_DIR_OVERRIDE: OnceLock<RwLock<Option<PathBuf>>> = OnceLock::new();

fn magi_base_dir_override() -> &'static RwLock<Option<PathBuf>> {
    MAGI_BASE_DIR_OVERRIDE.get_or_init(|| RwLock::new(None))
}

#[doc(hidden)]
pub fn set_magi_base_dir_override_for_tests(path: Option<PathBuf>) -> Option<PathBuf> {
    let mut guard = magi_base_dir_override()
        .write()
        .expect("lock Magi base dir override");
    std::mem::replace(&mut *guard, path)
}

#[cfg(test)]
static MAGI_BASE_DIR_OVERRIDE_TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

#[cfg(test)]
pub fn magi_base_dir_override_test_lock() -> MutexGuard<'static, ()> {
    MAGI_BASE_DIR_OVERRIDE_TEST_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .expect("lock Magi base dir override test mutex")
}

#[cfg(test)]
mod data_root_tests {
    use super::resolve_magi_base_dir;
    use std::path::Path;

    #[test]
    fn selects_dedicated_data_root_without_changing_home() {
        let home = std::env::temp_dir().join("magi-test-user");
        let candidate = home.join("candidate");
        assert_eq!(
            resolve_magi_base_dir(None, &home).unwrap(),
            home.join(".magi")
        );
        assert_eq!(
            resolve_magi_base_dir(candidate.to_str(), &home).unwrap(),
            candidate
        );
        for invalid in ["", "relative", home.to_str().unwrap()] {
            assert!(resolve_magi_base_dir(Some(invalid), &home).is_err());
        }
        let root = home.ancestors().last().unwrap();
        assert!(resolve_magi_base_dir(root.to_str(), &home).is_err());
        assert!(resolve_magi_base_dir(Some("/tmp/../"), Path::new("/users/test")).is_err());
    }
}
