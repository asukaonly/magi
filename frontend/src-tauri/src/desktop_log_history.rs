use log::{LevelFilter, Log, Metadata, Record};
use serde::Serialize;
use std::collections::BTreeSet;
use std::fs::{self, File, Metadata as FsMetadata, OpenOptions};
use std::io::{self, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard};

const DESKTOP_LOG_FILE_NAME: &str = "desktop.log";
const LEGACY_DESKTOP_LOG_PREFIX: &str = "desktop_";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopLogClearResult {
    pub cleared_entries: usize,
    pub failed_entries: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FileIdentity {
    first: u64,
    second: u64,
}

#[cfg(unix)]
fn file_identity(file: &File) -> io::Result<FileIdentity> {
    use std::os::unix::fs::MetadataExt;

    let metadata = file.metadata()?;
    Ok(FileIdentity {
        first: metadata.dev(),
        second: metadata.ino(),
    })
}

#[cfg(windows)]
fn windows_file_information(
    file: &File,
) -> io::Result<windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };

    let mut information = BY_HANDLE_FILE_INFORMATION::default();
    let result = unsafe {
        GetFileInformationByHandle(
            file.as_raw_handle() as windows_sys::Win32::Foundation::HANDLE,
            &mut information,
        )
    };
    if result == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(information)
    }
}

#[cfg(windows)]
fn file_identity(file: &File) -> io::Result<FileIdentity> {
    let information = windows_file_information(file)?;
    Ok(FileIdentity {
        first: u64::from(information.dwVolumeSerialNumber),
        second: (u64::from(information.nFileIndexHigh) << 32)
            | u64::from(information.nFileIndexLow),
    })
}

#[cfg(not(any(unix, windows)))]
fn file_identity(_file: &File) -> io::Result<FileIdentity> {
    Err(io::Error::other("file identity is unavailable"))
}

#[cfg(unix)]
fn has_single_link(file: &File) -> bool {
    use std::os::unix::fs::MetadataExt;

    file.metadata()
        .map(|metadata| metadata.nlink() == 1)
        .unwrap_or(false)
}

#[cfg(windows)]
fn has_single_link(file: &File) -> bool {
    windows_file_information(file)
        .map(|information| information.nNumberOfLinks == 1)
        .unwrap_or(false)
}

#[cfg(not(any(unix, windows)))]
fn has_single_link(_file: &File) -> bool {
    false
}

#[cfg(windows)]
fn opened_handle_is_reparse(file: &File) -> bool {
    use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;

    windows_file_information(file)
        .map(|information| information.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0)
        .unwrap_or(true)
}

#[cfg(not(windows))]
fn opened_handle_is_reparse(_file: &File) -> bool {
    false
}

#[cfg(windows)]
fn is_link_or_reparse(metadata: &FsMetadata) -> bool {
    use std::os::windows::fs::MetadataExt;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    metadata.file_type().is_symlink()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
fn is_link_or_reparse(metadata: &FsMetadata) -> bool {
    metadata.file_type().is_symlink()
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

fn open_log_root(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_DIRECTORY);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        use windows_sys::Win32::Storage::FileSystem::{
            FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAG_OPEN_REPARSE_POINT,
        };
        options.custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT);
    }
    options.open(path)
}

fn validate_log_root(path: &Path) -> io::Result<FileIdentity> {
    let metadata = fs::symlink_metadata(path)?;
    if is_link_or_reparse(&metadata) || !metadata.is_dir() {
        return Err(io::Error::other(
            "desktop log root must be a real directory",
        ));
    }
    let directory = open_log_root(path)?;
    if !directory.metadata()?.is_dir() || opened_handle_is_reparse(&directory) {
        return Err(io::Error::other(
            "desktop log root must be a real directory",
        ));
    }
    let identity = file_identity(&directory)?;
    let verifier = open_log_root(path)?;
    let current_metadata = fs::symlink_metadata(path)?;
    if is_link_or_reparse(&current_metadata)
        || !current_metadata.is_dir()
        || opened_handle_is_reparse(&verifier)
        || file_identity(&verifier)? != identity
    {
        return Err(io::Error::other(
            "desktop log root changed while it was validated",
        ));
    }
    Ok(identity)
}

fn root_identity_matches(path: &Path, expected: FileIdentity) -> bool {
    validate_log_root(path).ok() == Some(expected)
}

fn configure_log_file_options(options: &mut OpenOptions) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
        options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    }
}

fn open_existing_log_file(path: &Path, write: bool) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(write);
    configure_log_file_options(&mut options);
    options.open(path)
}

fn verify_open_log_file(path: &Path, file: &File) -> io::Result<()> {
    let path_metadata = fs::symlink_metadata(path)?;
    if is_link_or_reparse(&path_metadata)
        || !path_metadata.is_file()
        || !file.metadata()?.is_file()
        || opened_handle_is_reparse(file)
        || !has_single_link(file)
    {
        return Err(io::Error::other(
            "desktop log file must be a single-link regular file",
        ));
    }
    let identity = file_identity(file)?;
    let verifier = open_existing_log_file(path, false)?;
    let current_metadata = fs::symlink_metadata(path)?;
    if is_link_or_reparse(&current_metadata)
        || !current_metadata.is_file()
        || opened_handle_is_reparse(&verifier)
        || !has_single_link(&verifier)
        || file_identity(&verifier)? != identity
    {
        return Err(io::Error::other(
            "desktop log file changed while it was validated",
        ));
    }
    Ok(())
}

fn open_log_file(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.create(true).read(true).write(true);
    configure_log_file_options(&mut options);
    let file = options.open(path)?;
    verify_open_log_file(path, &file)?;
    Ok(file)
}

struct ActiveLogFile {
    file: File,
    path: PathBuf,
    current_size: u64,
    max_size: u64,
}

impl ActiveLogFile {
    fn open(log_dir: &Path, max_size: u64) -> io::Result<(Self, FileIdentity)> {
        fs::create_dir_all(log_dir)?;
        let log_root_identity = validate_log_root(log_dir)?;
        let path = log_dir.join(DESKTOP_LOG_FILE_NAME);
        let file = open_log_file(&path)?;
        if !root_identity_matches(log_dir, log_root_identity) {
            return Err(io::Error::other(
                "desktop log root changed while opening the active file",
            ));
        }
        let current_size = file.metadata()?.len();
        Ok((
            Self {
                file,
                path,
                current_size,
                max_size,
            },
            log_root_identity,
        ))
    }

    fn write_record(&mut self, buffer: &[u8]) -> io::Result<()> {
        let metadata = self.file.metadata()?;
        if !metadata.is_file() || !has_single_link(&self.file) {
            return Err(io::Error::other(
                "active desktop log file is no longer a single-link regular file",
            ));
        }
        if self.current_size != 0
            && self.current_size.saturating_add(buffer.len() as u64) > self.max_size
        {
            self.truncate()?;
        }
        self.file.seek(SeekFrom::End(0))?;
        self.file.write_all(buffer)?;
        self.file.flush()?;
        self.current_size = self.current_size.saturating_add(buffer.len() as u64);
        Ok(())
    }

    fn truncate(&mut self) -> io::Result<()> {
        let metadata = self.file.metadata()?;
        if !metadata.is_file() || !has_single_link(&self.file) {
            return Err(io::Error::other(
                "active desktop log file is no longer a single-link regular file",
            ));
        }
        self.file.flush()?;
        self.file.set_len(0)?;
        self.file.seek(SeekFrom::Start(0))?;
        self.file.sync_all()?;
        self.current_size = 0;
        Ok(())
    }
}

struct DesktopLogWriter {
    active: Arc<Mutex<ActiveLogFile>>,
    buffer: Vec<u8>,
}

impl Write for DesktopLogWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        self.buffer.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        if self.buffer.is_empty() {
            return Ok(());
        }
        let result = lock_unpoisoned(&self.active).write_record(&self.buffer);
        if result.is_ok() {
            self.buffer.clear();
        }
        result
    }
}

struct SynchronizedLogger {
    gate: Arc<Mutex<()>>,
    inner: Box<dyn Log>,
}

impl Log for SynchronizedLogger {
    fn enabled(&self, metadata: &Metadata<'_>) -> bool {
        self.inner.enabled(metadata)
    }

    fn log(&self, record: &Record<'_>) {
        let _guard = lock_unpoisoned(&self.gate);
        self.inner.log(record);
    }

    fn flush(&self) {
        let _guard = lock_unpoisoned(&self.gate);
        self.inner.flush();
    }
}

pub struct DesktopLogRuntime {
    gate: Arc<Mutex<()>>,
    active: Arc<Mutex<ActiveLogFile>>,
    log_dir: PathBuf,
    log_root_identity: FileIdentity,
    backend_log_path: PathBuf,
}

impl DesktopLogRuntime {
    fn build(
        log_dir: PathBuf,
        backend_log_path: PathBuf,
        max_size: u64,
        level: LevelFilter,
    ) -> Result<(Self, SynchronizedLogger, LevelFilter), String> {
        let (active_file, log_root_identity) = ActiveLogFile::open(&log_dir, max_size)
            .map_err(|error| format!("Failed to open desktop log file: {error}"))?;
        let active = Arc::new(Mutex::new(active_file));
        let gate = Arc::new(Mutex::new(()));
        let writer = DesktopLogWriter {
            active: Arc::clone(&active),
            buffer: Vec::new(),
        };
        let (max_level, inner) = tauri_plugin_log::fern::Dispatch::new()
            .format(|out, message, record| {
                let now = tauri_plugin_log::TimezoneStrategy::UseLocal.get_now();
                out.finish(format_args!(
                    "[{} {}][{}][{}] {}",
                    now.date(),
                    now.time(),
                    record.target(),
                    record.level(),
                    message
                ));
            })
            .level(level)
            .chain(tauri_plugin_log::fern::Output::writer(
                Box::new(writer),
                "\n",
            ))
            .chain(std::io::stdout())
            .into_log();

        Ok((
            Self {
                gate: Arc::clone(&gate),
                active,
                log_dir,
                log_root_identity,
                backend_log_path,
            },
            SynchronizedLogger { gate, inner },
            max_level,
        ))
    }

    pub fn install(
        log_dir: PathBuf,
        backend_log_path: PathBuf,
        max_size: u64,
        level: LevelFilter,
    ) -> Result<Self, String> {
        let (runtime, logger, max_level) = Self::build(log_dir, backend_log_path, max_size, level)?;
        log::set_boxed_logger(Box::new(logger))
            .map_err(|error| format!("Failed to install desktop logger: {error}"))?;
        log::set_max_level(max_level);
        Ok(runtime)
    }

    pub fn clear(&self) -> DesktopLogClearResult {
        let _guard = lock_unpoisoned(&self.gate);
        let mut cleared_entries = 0;
        let mut failed_entries = 0;

        let active_path = {
            let mut active = lock_unpoisoned(&self.active);
            let path = active.path.clone();
            if active.truncate().is_ok() {
                cleared_entries += 1;
            } else {
                failed_entries += 1;
            }
            path
        };

        if !root_identity_matches(&self.log_dir, self.log_root_identity) {
            failed_entries += 1;
        } else {
            let (cleared, failed) =
                clear_legacy_desktop_logs(&self.log_dir, self.log_root_identity, &active_path);
            cleared_entries += cleared;
            failed_entries += failed;
        }

        if !self.backend_log_path.starts_with(&self.log_dir)
            || root_identity_matches(&self.log_dir, self.log_root_identity)
        {
            match clear_known_log_path(&self.backend_log_path, self.backend_log_path.parent(), None)
            {
                Ok(true) => cleared_entries += 1,
                Ok(false) => {}
                Err(()) => failed_entries += 1,
            }
        }

        DesktopLogClearResult {
            cleared_entries,
            failed_entries,
        }
    }
}

fn clear_legacy_desktop_logs(
    log_dir: &Path,
    expected_root: FileIdentity,
    active_path: &Path,
) -> (usize, usize) {
    let entries = match fs::read_dir(log_dir) {
        Ok(entries) => entries,
        Err(_) => return (0, 1),
    };
    let mut candidates = BTreeSet::new();
    let mut failed = 0;
    for entry in entries {
        let entry = match entry {
            Ok(entry) => entry,
            Err(_) => {
                failed += 1;
                continue;
            }
        };
        let path = entry.path();
        if path == active_path {
            continue;
        }
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if name.starts_with(LEGACY_DESKTOP_LOG_PREFIX)
            && (name.ends_with(".log") || name.ends_with(".log.bak"))
        {
            candidates.insert(path);
        }
    }

    let mut cleared = 0;
    for path in candidates {
        match clear_known_log_path(&path, Some(log_dir), Some(expected_root)) {
            Ok(true) => cleared += 1,
            Ok(false) => {}
            Err(()) => failed += 1,
        }
    }
    (cleared, failed)
}

fn clear_known_log_path(
    path: &Path,
    parent: Option<&Path>,
    expected_parent: Option<FileIdentity>,
) -> Result<bool, ()> {
    let parent = parent.ok_or(())?;
    let parent_identity = expected_parent.or_else(|| validate_log_root(parent).ok());
    let parent_identity = parent_identity.ok_or(())?;
    if !root_identity_matches(parent, parent_identity) {
        return Err(());
    }

    let path_metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(_) => return Err(()),
    };
    if is_link_or_reparse(&path_metadata) || !path_metadata.is_file() {
        return Err(());
    }

    let mut file = open_existing_log_file(path, true).map_err(|_| ())?;
    verify_open_log_file(path, &file).map_err(|_| ())?;
    if !root_identity_matches(parent, parent_identity) || !has_single_link(&file) {
        return Err(());
    }
    file.flush().map_err(|_| ())?;
    file.set_len(0).map_err(|_| ())?;
    file.seek(SeekFrom::Start(0)).map_err(|_| ())?;
    file.sync_all().map_err(|_| ())?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::{DesktopLogRuntime, DesktopLogWriter, SynchronizedLogger, DESKTOP_LOG_FILE_NAME};
    use log::{Level, LevelFilter, Log, Metadata, Record};
    use std::fs;
    use std::io::Write;
    use std::path::PathBuf;
    use std::sync::{mpsc, Arc, Barrier, Mutex};
    use std::thread;
    use std::time::Duration;

    fn test_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "magi-desktop-log-{name}-{}-{:?}",
            std::process::id(),
            thread::current().id()
        ))
    }

    fn build_runtime(root: &PathBuf, max_size: u64) -> (DesktopLogRuntime, impl Log) {
        let log_dir = root.join("logs");
        let backend_log = log_dir.join("backend.log");
        let (runtime, logger, _) =
            DesktopLogRuntime::build(log_dir, backend_log, max_size, LevelFilter::Trace).unwrap();
        (runtime, logger)
    }

    fn write_log(logger: &impl Log, message: &str) {
        logger.log(
            &Record::builder()
                .level(Level::Info)
                .target("desktop-test")
                .args(format_args!("{message}"))
                .build(),
        );
        logger.flush();
    }

    #[test]
    fn clears_active_legacy_and_backend_logs_then_keeps_logging() {
        let root = test_root("clear");
        let _ = fs::remove_dir_all(&root);
        let (runtime, logger) = build_runtime(&root, 1024);
        let log_dir = root.join("logs");
        write_log(&logger, "old desktop content");
        fs::write(log_dir.join("desktop_2026-07-31.log"), "old archive").unwrap();
        fs::write(
            log_dir.join("desktop_2026-07-31.log.bak"),
            "old collision archive",
        )
        .unwrap();
        fs::write(log_dir.join("backend.log"), "old sidecar output").unwrap();

        let result = runtime.clear();

        assert_eq!(result.failed_entries, 0);
        assert_eq!(result.cleared_entries, 4);
        assert_eq!(
            fs::read_to_string(log_dir.join(DESKTOP_LOG_FILE_NAME)).unwrap(),
            ""
        );
        assert_eq!(
            fs::read_to_string(log_dir.join("desktop_2026-07-31.log")).unwrap(),
            ""
        );
        assert_eq!(
            fs::read_to_string(log_dir.join("desktop_2026-07-31.log.bak")).unwrap(),
            ""
        );
        assert_eq!(fs::read_to_string(log_dir.join("backend.log")).unwrap(), "");

        write_log(&logger, "fresh desktop content");
        let refreshed = fs::read_to_string(log_dir.join(DESKTOP_LOG_FILE_NAME)).unwrap();
        assert!(refreshed.contains("fresh desktop content"));
        assert!(!refreshed.contains("old desktop content"));

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn clearing_resets_rotation_size_state() {
        let root = test_root("rotation");
        let _ = fs::remove_dir_all(&root);
        let (runtime, logger) = build_runtime(&root, 600);
        let active = root.join("logs").join(DESKTOP_LOG_FILE_NAME);
        write_log(&logger, &"old".repeat(100));

        assert_eq!(runtime.clear().failed_entries, 0);
        write_log(&logger, &"fresh".repeat(60));

        let text = fs::read_to_string(&active).unwrap();
        assert!(text.contains("fresh"));
        assert!(!text.contains("oldold"));
        let _ = fs::remove_dir_all(&root);
    }

    #[cfg(unix)]
    #[test]
    fn rejects_legacy_hard_links_without_touching_the_outside_file() {
        let root = test_root("hard-link");
        let _ = fs::remove_dir_all(&root);
        let (runtime, _logger) = build_runtime(&root, 1024);
        let outside = root.join("outside.txt");
        fs::write(&outside, "must stay").unwrap();
        fs::hard_link(&outside, root.join("logs").join("desktop_old.log")).unwrap();

        let result = runtime.clear();

        assert_eq!(result.failed_entries, 1);
        assert_eq!(fs::read_to_string(&outside).unwrap(), "must stay");
        let _ = fs::remove_dir_all(&root);
    }

    #[cfg(unix)]
    #[test]
    fn refuses_to_truncate_an_active_log_with_an_outside_hard_link() {
        let root = test_root("active-hard-link");
        let _ = fs::remove_dir_all(&root);
        let (runtime, logger) = build_runtime(&root, 1024);
        let active = root.join("logs").join(DESKTOP_LOG_FILE_NAME);
        write_log(&logger, "old desktop content");
        let outside_link = root.join("outside-desktop.log");
        fs::hard_link(&active, &outside_link).unwrap();

        let result = runtime.clear();

        assert_eq!(result.failed_entries, 1);
        assert!(fs::read_to_string(&active)
            .unwrap()
            .contains("old desktop content"));
        assert!(fs::read_to_string(&outside_link)
            .unwrap()
            .contains("old desktop content"));
        let _ = fs::remove_dir_all(&root);
    }

    #[cfg(unix)]
    #[test]
    fn clears_the_owned_handle_but_rejects_a_replaced_log_directory() {
        let root = test_root("replaced-root");
        let _ = fs::remove_dir_all(&root);
        let (runtime, logger) = build_runtime(&root, 1024);
        let log_dir = root.join("logs");
        let moved_dir = root.join("logs-old");
        write_log(&logger, "old desktop content");
        fs::rename(&log_dir, &moved_dir).unwrap();
        fs::create_dir_all(&log_dir).unwrap();
        fs::write(log_dir.join(DESKTOP_LOG_FILE_NAME), "untrusted replacement").unwrap();

        let result = runtime.clear();

        assert!(result.failed_entries > 0);
        assert_eq!(
            fs::read_to_string(moved_dir.join(DESKTOP_LOG_FILE_NAME)).unwrap(),
            ""
        );
        assert_eq!(
            fs::read_to_string(log_dir.join(DESKTOP_LOG_FILE_NAME)).unwrap(),
            "untrusted replacement"
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[cfg(unix)]
    #[test]
    fn refuses_a_symlinked_log_directory_at_startup() {
        use std::os::unix::fs::symlink;

        let root = test_root("root-symlink");
        let _ = fs::remove_dir_all(&root);
        let outside = root.join("outside");
        fs::create_dir_all(&outside).unwrap();
        symlink(&outside, root.join("logs")).unwrap();

        assert!(DesktopLogRuntime::build(
            root.join("logs"),
            root.join("logs").join("backend.log"),
            1024,
            LevelFilter::Info,
        )
        .is_err());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn concurrent_clear_operations_remain_serialized() {
        let root = test_root("concurrent-clear");
        let _ = fs::remove_dir_all(&root);
        let (runtime, logger) = build_runtime(&root, 1024);
        write_log(&logger, "old desktop content");
        let runtime = Arc::new(runtime);
        let start = Arc::new(Barrier::new(3));
        let mut joins = Vec::new();
        for _ in 0..2 {
            let runtime = Arc::clone(&runtime);
            let start = Arc::clone(&start);
            joins.push(thread::spawn(move || {
                start.wait();
                runtime.clear()
            }));
        }
        start.wait();

        for join in joins {
            assert_eq!(join.join().unwrap().failed_entries, 0);
        }
        write_log(&logger, "fresh desktop content");
        let text = fs::read_to_string(root.join("logs").join(DESKTOP_LOG_FILE_NAME)).unwrap();
        assert!(text.contains("fresh desktop content"));
        assert!(!text.contains("old desktop content"));
        let _ = fs::remove_dir_all(&root);
    }

    struct BlockingLogger {
        entered: mpsc::Sender<()>,
        release: Mutex<mpsc::Receiver<()>>,
        writer: Mutex<DesktopLogWriter>,
    }

    impl Log for BlockingLogger {
        fn enabled(&self, _metadata: &Metadata<'_>) -> bool {
            true
        }

        fn log(&self, record: &Record<'_>) {
            self.entered.send(()).unwrap();
            self.release.lock().unwrap().recv().unwrap();
            let mut writer = self.writer.lock().unwrap();
            write!(writer, "{}", record.args()).unwrap();
            writer.flush().unwrap();
        }

        fn flush(&self) {}
    }

    #[test]
    fn clear_waits_for_an_in_flight_log_write_before_truncating() {
        let root = test_root("in-flight-write");
        let _ = fs::remove_dir_all(&root);
        let (runtime, _unused_logger) = build_runtime(&root, 1024);
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let logger = SynchronizedLogger {
            gate: Arc::clone(&runtime.gate),
            inner: Box::new(BlockingLogger {
                entered: entered_tx,
                release: Mutex::new(release_rx),
                writer: Mutex::new(DesktopLogWriter {
                    active: Arc::clone(&runtime.active),
                    buffer: Vec::new(),
                }),
            }),
        };
        let log_thread = thread::spawn(move || write_log(&logger, "old queued content"));
        entered_rx.recv().unwrap();

        let runtime = Arc::new(runtime);
        let (cleared_tx, cleared_rx) = mpsc::channel();
        let clear_runtime = Arc::clone(&runtime);
        let clear_thread = thread::spawn(move || {
            let result = clear_runtime.clear();
            cleared_tx.send(result).unwrap();
        });
        assert!(cleared_rx.recv_timeout(Duration::from_millis(50)).is_err());

        release_tx.send(()).unwrap();
        log_thread.join().unwrap();
        let result = cleared_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        clear_thread.join().unwrap();

        assert_eq!(result.failed_entries, 0);
        assert_eq!(
            fs::read_to_string(root.join("logs").join(DESKTOP_LOG_FILE_NAME)).unwrap(),
            ""
        );
        let _ = fs::remove_dir_all(&root);
    }
}
