//! Independent Unix worker-family teardown when its gateway disappears.

use std::ffi::CString;
use std::io::{self, Read};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::{ffi::OsStrExt, process::CommandExt};
use std::path::Path;
use std::process::Command;
use std::time::Duration;

/// Only the gateway retains this pipe's writer. The guardian survives its death.
pub struct WorkerGuardian {
    _lifetime: OwnedFd,
}

impl WorkerGuardian {
    pub fn prepare(command: &mut Command, executable: &Path, drain_secs: u64) -> io::Result<Self> {
        let executable = CString::new(executable.as_os_str().as_bytes())?;
        let mode = CString::new("worker-guardian")?;
        let timeout_flag = CString::new("--drain-secs")?;
        let timeout = CString::new(drain_secs.to_string())?;
        let mut descriptors = [-1; 2];
        if unsafe { libc::pipe(descriptors.as_mut_ptr()) } != 0 {
            return Err(io::Error::last_os_error());
        }
        let reader = unsafe { OwnedFd::from_raw_fd(descriptors[0]) };
        let writer = unsafe { OwnedFd::from_raw_fd(descriptors[1]) };
        for descriptor in [&reader, &writer] {
            if unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_SETFD, libc::FD_CLOEXEC) } < 0 {
                return Err(io::Error::last_os_error());
            }
        }
        let write_fd = writer.as_raw_fd();
        command.process_group(0);
        // SAFETY: after fork, this hook uses only async-signal-safe libc calls.
        // The helper exec closes every inherited CLOEXEC lease/listener. It stays
        // in the worker's process group, so that group's identity cannot be reused.
        unsafe {
            command.pre_exec(move || {
                libc::close(write_fd);
                // Block termination until the helper can inherit an ignored
                // disposition across exec. The worker restores its original mask.
                let mut blocked = std::mem::zeroed::<libc::sigset_t>();
                let mut original = std::mem::zeroed::<libc::sigset_t>();
                libc::sigemptyset(&mut blocked);
                libc::sigaddset(&mut blocked, libc::SIGTERM);
                if libc::sigprocmask(libc::SIG_BLOCK, &blocked, &mut original) != 0 {
                    return Err(io::Error::last_os_error());
                }
                let guardian = libc::fork();
                if guardian < 0 {
                    let error = io::Error::last_os_error();
                    libc::sigprocmask(libc::SIG_SETMASK, &original, std::ptr::null_mut());
                    return Err(error);
                }
                if guardian == 0 {
                    if libc::signal(libc::SIGTERM, libc::SIG_IGN) == libc::SIG_ERR
                        || libc::sigprocmask(libc::SIG_SETMASK, &original, std::ptr::null_mut())
                            != 0
                        || libc::dup2(reader.as_raw_fd(), libc::STDIN_FILENO) < 0
                    {
                        libc::kill(-libc::getpgrp(), libc::SIGKILL);
                        libc::_exit(127);
                    }
                    libc::close(libc::STDOUT_FILENO);
                    libc::close(libc::STDERR_FILENO);
                    let arguments = [
                        executable.as_ptr(),
                        mode.as_ptr(),
                        timeout_flag.as_ptr(),
                        timeout.as_ptr(),
                        std::ptr::null(),
                    ];
                    libc::execv(executable.as_ptr(), arguments.as_ptr());
                    // Never leave a worker running without its required guardian.
                    libc::kill(-libc::getpgrp(), libc::SIGKILL);
                    libc::_exit(127);
                }
                libc::close(reader.as_raw_fd());
                if libc::sigprocmask(libc::SIG_SETMASK, &original, std::ptr::null_mut()) != 0 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        Ok(Self { _lifetime: writer })
    }
}

/// Internal helper entry. No Python execution or runtime lease is involved.
pub fn run(drain_secs: u64) -> Result<(), String> {
    if !(1..=60).contains(&drain_secs) {
        return Err("Worker guardian deadline is out of range".into());
    }
    let group = unsafe { libc::getpgrp() };
    if group <= 1 || group == unsafe { libc::getpid() } {
        return Err("Worker guardian requires its inherited worker process group".into());
    }
    // A normal terminal cannot serve as the private lifetime pipe.
    let mut metadata = std::mem::MaybeUninit::<libc::stat>::uninit();
    if unsafe { libc::fstat(libc::STDIN_FILENO, metadata.as_mut_ptr()) } != 0
        || unsafe { metadata.assume_init() }.st_mode & libc::S_IFMT != libc::S_IFIFO
    {
        return Err("Worker guardian requires a private lifetime pipe".into());
    }
    // Normal worker shutdown signals the same group. The guardian must survive
    // that drain in case the gateway disappears before its final SIGKILL.
    unsafe { libc::signal(libc::SIGTERM, libc::SIG_IGN) };
    let mut byte = [0u8; 1];
    loop {
        match io::stdin().read(&mut byte) {
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            _ => break,
        }
    }
    unsafe {
        libc::kill(-group, libc::SIGTERM);
    }
    std::thread::sleep(Duration::from_secs(drain_secs));
    unsafe {
        libc::kill(-group, libc::SIGKILL);
    }
    Ok(())
}
