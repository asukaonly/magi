//! Explicit lifecycle commands own their progress; interactive prompts keep their renderer.

use std::{
    io::IsTerminal,
    sync::{mpsc, Mutex},
    time::{Duration, Instant},
};

pub fn run<T>(operation: impl FnOnce(&dyn Fn(&str)) -> Result<T, String>) -> Result<T, String> {
    if !std::io::stderr().is_terminal() {
        return operation(&|_| {});
    }
    report(
        operation,
        &|message| eprintln!("{message}"),
        Duration::from_secs(5),
    )
}

fn report<T>(
    operation: impl FnOnce(&dyn Fn(&str)) -> Result<T, String>,
    emit: &(dyn Fn(&str) + Sync),
    interval: Duration,
) -> Result<T, String> {
    let started = Instant::now();
    let stage = Mutex::new(String::from("Checking background service ownership"));
    let (done, stopping) = mpsc::channel();
    std::thread::scope(|scope| {
        let done = done;
        let current_stage = &stage;
        let ticker = scope.spawn(move || {
            while stopping
                .recv_timeout(interval)
                .is_err_and(|e| e == mpsc::RecvTimeoutError::Timeout)
            {
                if let Ok(stage) = current_stage.lock() {
                    emit(&format!(
                        "  {}s elapsed - {stage}",
                        started.elapsed().as_secs()
                    ));
                }
            }
        });
        let update = |message: &str| {
            if let Ok(mut stage) = stage.lock() {
                *stage = message.into();
            }
            emit(message);
        };
        let result = operation(&update);
        let _ = done.send(());
        let _ = ticker.join();
        if result.is_ok() {
            emit(&format!(
                "Service command completed in {:.1}s.",
                started.elapsed().as_secs_f64()
            ));
        } else {
            emit(&format!(
                "Service command did not complete ({:.1}s elapsed).",
                started.elapsed().as_secs_f64()
            ));
        }
        result
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn long_operation_reports_its_stage_and_stops_ticking_on_failure() {
        let lines = Mutex::new(Vec::<String>::new());
        let (tick, ticked) = mpsc::channel();
        let emit = |line: &str| {
            lines.lock().unwrap().push(line.into());
            if line.contains("elapsed -") {
                let _ = tick.send(());
            }
        };
        let result: Result<(), String> = report(
            |update| {
                update("Waiting for macOS to unload the job");
                ticked.recv_timeout(Duration::from_secs(2)).unwrap();
                Err("Timed out".into())
            },
            &emit,
            Duration::from_millis(10),
        );
        assert_eq!(result.unwrap_err(), "Timed out");
        let lines = lines.lock().unwrap();
        assert_eq!(
            lines.first().unwrap(),
            "Waiting for macOS to unload the job"
        );
        assert!(lines
            .iter()
            .any(|l| l.contains("elapsed - Waiting for macOS")));
        assert!(lines.last().unwrap().contains("did not complete"));
        assert!(!lines.iter().any(|l| l.contains("command completed")));
    }
}
