#[cfg(target_os = "macos")]
use std::path::{Path, PathBuf};

#[cfg(target_os = "macos")]
const INSTALLER_VOLUME_PATH: &str = "/Volumes/Magi";

#[cfg(target_os = "macos")]
const DETACH_RETRIES: usize = 8;

#[cfg(target_os = "macos")]
const DETACH_RETRY_DELAY: std::time::Duration = std::time::Duration::from_secs(1);

#[cfg(target_os = "macos")]
pub fn detach_installer_volume_after_launch() {
    let volume_path = PathBuf::from(INSTALLER_VOLUME_PATH);
    let Ok(current_exe) = std::env::current_exe() else {
        return;
    };

    if !should_detach_installer_volume(&current_exe, &volume_path, volume_path.exists()) {
        return;
    }

    std::thread::spawn(move || {
        for _ in 0..DETACH_RETRIES {
            if !volume_path.exists() {
                return;
            }

            let status = std::process::Command::new("hdiutil")
                .arg("detach")
                .arg(&volume_path)
                .arg("-quiet")
                .status();

            if matches!(status, Ok(exit_status) if exit_status.success()) || !volume_path.exists() {
                return;
            }

            std::thread::sleep(DETACH_RETRY_DELAY);
        }
    });
}

#[cfg(target_os = "macos")]
fn should_detach_installer_volume(
    current_exe: &Path,
    volume_path: &Path,
    volume_exists: bool,
) -> bool {
    volume_exists && !current_exe.starts_with(volume_path)
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::should_detach_installer_volume;
    use std::path::Path;

    #[test]
    fn skips_detach_when_app_runs_from_installer_volume() {
        assert!(!should_detach_installer_volume(
            Path::new("/Volumes/Magi/Magi.app/Contents/MacOS/magi-desktop"),
            Path::new("/Volumes/Magi"),
            true
        ));
    }

    #[test]
    fn detaches_when_app_runs_from_applications() {
        assert!(should_detach_installer_volume(
            Path::new("/Applications/Magi.app/Contents/MacOS/magi-desktop"),
            Path::new("/Volumes/Magi"),
            true
        ));
    }

    #[test]
    fn skips_detach_when_installer_volume_is_not_mounted() {
        assert!(!should_detach_installer_volume(
            Path::new("/Applications/Magi.app/Contents/MacOS/magi-desktop"),
            Path::new("/Volumes/Magi"),
            false
        ));
    }
}
