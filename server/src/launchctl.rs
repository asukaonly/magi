//! Bounded OS service-manager calls; a hung helper cannot stall the console forever.

use std::{
    path::Path,
    process::{Output, Stdio},
    time::Duration,
};
use tokio::io::{AsyncRead, AsyncReadExt};

const OUTPUT_LIMIT: usize = 64 * 1024;
pub const INSPECT_TIMEOUT: Duration = Duration::from_secs(5);
pub const CONTROL_TIMEOUT: Duration = Duration::from_secs(10);

pub fn output(args: &[&str], timeout: Duration) -> Result<Output, String> {
    let operation = args.first().copied().unwrap_or("command");
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| e.to_string())?
        .block_on(run(Path::new("/bin/launchctl"), args, timeout))
        .map_err(|error| format!("launchctl {operation}: {error}"))
}

async fn read_output(mut reader: impl AsyncRead + Unpin) -> std::io::Result<(Vec<u8>, bool)> {
    let mut result = Vec::new();
    let mut truncated = false;
    let mut buffer = [0; 8192];
    loop {
        let count = reader.read(&mut buffer).await?;
        if count == 0 {
            return Ok((result, truncated));
        }
        let retained = count.min(OUTPUT_LIMIT - result.len());
        result.extend_from_slice(&buffer[..retained]);
        truncated |= retained < count;
    }
}

async fn run(program: &Path, args: &[&str], timeout: Duration) -> Result<Output, String> {
    let mut child = tokio::process::Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| e.to_string())?;
    let stdout = child.stdout.take().ok_or("Cannot capture helper output")?;
    let stderr = child.stderr.take().ok_or("Cannot capture helper errors")?;
    let result = tokio::time::timeout(timeout, async {
        tokio::try_join!(child.wait(), read_output(stdout), read_output(stderr))
    })
    .await;
    match result {
        Ok(Ok((status, (stdout, false), (stderr, false)))) => Ok(Output {
            status,
            stdout,
            stderr,
        }),
        Ok(Ok(_)) => {
            Err("Output exceeded the inspection limit; service state could not be verified".into())
        }
        Ok(Err(error)) => Err(error.to_string()),
        Err(_) => {
            let _ = child.start_kill();
            let _ = tokio::time::timeout(Duration::from_secs(1), child.wait()).await;
            Err(format!("Timed out after {:.1}s. The OS service request may still be completing; check status before retrying.", timeout.as_secs_f64()))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn captures_exit_status_and_both_streams() {
        let result = run(
            Path::new("/bin/sh"),
            &["-c", "printf ready; printf failed >&2; exit 113"],
            Duration::from_secs(2),
        )
        .await
        .unwrap();
        assert_eq!(result.status.code(), Some(113));
        assert_eq!(result.stdout, b"ready");
        assert_eq!(result.stderr, b"failed");
    }

    #[tokio::test]
    async fn hanging_helper_is_terminated_with_a_diagnostic() {
        let started = std::time::Instant::now();
        let result = run(
            Path::new("/bin/sh"),
            &["-c", "exec sleep 30"],
            Duration::from_millis(100),
        )
        .await;
        assert!(result.unwrap_err().contains("check status before retrying"));
        assert!(started.elapsed() < Duration::from_secs(3));
    }

    #[tokio::test]
    async fn oversized_output_is_drained_but_never_parsed_as_complete() {
        let result = run(
            Path::new("/bin/sh"),
            &[
                "-c",
                "i=0; while [ $i -lt 8193 ]; do printf 12345678; i=$((i+1)); done",
            ],
            Duration::from_secs(3),
        )
        .await;
        assert!(result.unwrap_err().contains("Output exceeded"));
    }
}
