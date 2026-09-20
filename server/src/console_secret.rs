//! Disable OS echo before a password prompt is rendered, including immediate pastes.

use std::io;

pub fn read<T>(operation: impl FnOnce() -> io::Result<T>) -> io::Result<T> {
    #[cfg(unix)]
    {
        without_echo(libc::STDIN_FILENO, operation)
    }
    #[cfg(not(unix))]
    {
        let _ = operation;
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "Console setup requires a Unix terminal",
        ))
    }
}

#[cfg(unix)]
fn without_echo<T>(
    fd: std::os::fd::RawFd,
    operation: impl FnOnce() -> io::Result<T>,
) -> io::Result<T> {
    struct Restore {
        fd: std::os::fd::RawFd,
        attributes: libc::termios,
    }
    impl Drop for Restore {
        fn drop(&mut self) {
            // SAFETY: the caller keeps this terminal open until the operation completes.
            unsafe {
                libc::tcsetattr(self.fd, libc::TCSANOW, &self.attributes);
            }
        }
    }
    let mut original = std::mem::MaybeUninit::uninit();
    // SAFETY: tcgetattr initializes the provided termios on success.
    if unsafe { libc::tcgetattr(fd, original.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let original = unsafe { original.assume_init() };
    let mut hidden = original;
    hidden.c_lflag &= !(libc::ECHO | libc::ECHONL);
    // Do not flush input: a paste may already be waiting for the prompt.
    if unsafe { libc::tcsetattr(fd, libc::TCSANOW, &hidden) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let _restore = Restore {
        fd,
        attributes: original,
    };
    operation()
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::fd::{FromRawFd, OwnedFd};

    #[test]
    fn echo_is_disabled_before_rendering_and_restored_after_cancel() {
        let (mut master, mut slave) = (0, 0);
        // SAFETY: output descriptors are initialized by openpty on success.
        assert_eq!(
            unsafe {
                libc::openpty(
                    &mut master,
                    &mut slave,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                )
            },
            0
        );
        let (_master, _slave) =
            unsafe { (OwnedFd::from_raw_fd(master), OwnedFd::from_raw_fd(slave)) };
        let flags = || {
            let mut value = std::mem::MaybeUninit::uninit();
            assert_eq!(unsafe { libc::tcgetattr(slave, value.as_mut_ptr()) }, 0);
            unsafe { value.assume_init().c_lflag }
        };
        let original = flags();
        for cancel in [false, true] {
            let result = without_echo(slave, || {
                assert_eq!(flags() & (libc::ECHO | libc::ECHONL), 0);
                if cancel {
                    Err(io::Error::from(io::ErrorKind::Interrupted))
                } else {
                    Ok(())
                }
            });
            assert_eq!(result.is_err(), cancel);
            assert_eq!(flags(), original);
        }
    }
}
