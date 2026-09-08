//! Capture managed-service diagnostics without leaving launchd-owned log handles.

#[cfg(not(unix))]
use std::path::Path;

#[cfg(unix)]
mod unix {
    use std::fs::File;
    use std::io::{self, Read, Write};
    use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
    use std::path::Path;
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    };

    use magi_server_runtime::logs::RotatingLog;

    pub struct ManagedOutput {
        stdout: OwnedFd,
        stderr: OwnedFd,
        stopping: Arc<AtomicBool>,
        reader: Option<std::thread::JoinHandle<()>>,
    }

    fn duplicate(fd: i32) -> io::Result<OwnedFd> {
        let copied = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 3) };
        if copied < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(unsafe { OwnedFd::from_raw_fd(copied) })
    }

    impl ManagedOutput {
        pub fn start(path: &Path) -> io::Result<Self> {
            if !path.is_absolute() {
                return Err(io::Error::other("Output log path must be absolute"));
            }
            let mut log = RotatingLog::open(path)?;
            let stdout = duplicate(libc::STDOUT_FILENO)?;
            let stderr = duplicate(libc::STDERR_FILENO)?;
            let mut descriptors = [-1; 2];
            if unsafe { libc::pipe(descriptors.as_mut_ptr()) } != 0 {
                return Err(io::Error::last_os_error());
            }
            let read = unsafe { OwnedFd::from_raw_fd(descriptors[0]) };
            let write = unsafe { OwnedFd::from_raw_fd(descriptors[1]) };
            for fd in [&read, &write] {
                if unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_SETFD, libc::FD_CLOEXEC) } < 0 {
                    return Err(io::Error::last_os_error());
                }
            }
            if unsafe { libc::fcntl(read.as_raw_fd(), libc::F_SETFL, libc::O_NONBLOCK) } < 0 {
                return Err(io::Error::last_os_error());
            }
            let stopping = Arc::new(AtomicBool::new(false));
            let stop = stopping.clone();
            let reader = std::thread::Builder::new()
                .name("magi-service-log".into())
                .spawn(move || {
                    let mut source = File::from(read);
                    let mut bytes = [0u8; 8192];
                    let mut closing_chunks = 0;
                    loop {
                        if stop.load(Ordering::Acquire) {
                            closing_chunks += 1;
                            if closing_chunks > 32 {
                                break;
                            }
                        }
                        match source.read(&mut bytes) {
                            Ok(0) => break,
                            Ok(count) => {
                                let _ = log.write_all(&bytes[..count]);
                            }
                            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                                if stop.load(Ordering::Acquire) {
                                    break;
                                }
                                let mut poll = libc::pollfd {
                                    fd: source.as_raw_fd(),
                                    events: libc::POLLIN,
                                    revents: 0,
                                };
                                unsafe {
                                    libc::poll(&mut poll, 1, 250);
                                }
                            }
                            Err(_) => break,
                        }
                    }
                    let _ = log.flush();
                })?;
            let guard = Self {
                stdout,
                stderr,
                stopping,
                reader: Some(reader),
            };
            for target in [libc::STDOUT_FILENO, libc::STDERR_FILENO] {
                if unsafe { libc::dup2(write.as_raw_fd(), target) } < 0 {
                    return Err(io::Error::last_os_error());
                }
            }
            Ok(guard)
        }
    }

    impl Drop for ManagedOutput {
        fn drop(&mut self) {
            let _ = io::stdout().flush();
            let _ = io::stderr().flush();
            unsafe {
                libc::dup2(self.stdout.as_raw_fd(), libc::STDOUT_FILENO);
                libc::dup2(self.stderr.as_raw_fd(), libc::STDERR_FILENO);
            }
            self.stopping.store(true, Ordering::Release);
            if let Some(reader) = self.reader.take() {
                let _ = reader.join();
            }
        }
    }
}

#[cfg(unix)]
pub use unix::ManagedOutput;

#[cfg(not(unix))]
pub struct ManagedOutput;

#[cfg(not(unix))]
impl ManagedOutput {
    pub fn start(_path: &Path) -> std::io::Result<Self> {
        Err(std::io::Error::other(
            "Managed service output requires a Unix host",
        ))
    }
}
