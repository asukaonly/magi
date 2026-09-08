//! Drain native database users before center maintenance.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, OnceLock,
};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

const CAPACITY: u32 = 1024;

pub struct DatabaseGate {
    closed: AtomicBool,
    slots: Arc<Semaphore>,
}

impl Default for DatabaseGate {
    fn default() -> Self {
        Self {
            closed: AtomicBool::new(false),
            slots: Arc::new(Semaphore::new(CAPACITY as usize)),
        }
    }
}

impl DatabaseGate {
    pub fn enter(&self) -> Option<OwnedSemaphorePermit> {
        if self.closed.load(Ordering::Acquire) {
            return None;
        }
        let permit = Arc::clone(&self.slots).try_acquire_owned().ok()?;
        if self.closed.load(Ordering::Acquire) {
            return None;
        }
        Some(permit)
    }

    pub fn close(&self) {
        self.closed.store(true, Ordering::Release);
    }
    pub fn reopen(&self) {
        self.closed.store(false, Ordering::Release);
    }

    pub async fn drain(&self) -> Result<OwnedSemaphorePermit, String> {
        self.close();
        Arc::clone(&self.slots)
            .acquire_many_owned(CAPACITY)
            .await
            .map_err(|_| "Native database gate is unavailable".into())
    }
}

pub fn global() -> &'static DatabaseGate {
    static GATE: OnceLock<DatabaseGate> = OnceLock::new();
    GATE.get_or_init(DatabaseGate::default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[tokio::test]
    async fn maintenance_waits_for_native_work_even_if_its_request_is_gone() {
        let gate = Arc::new(DatabaseGate::default());
        let operation = gate.enter().unwrap();
        gate.close();
        assert!(gate.enter().is_none());
        assert!(
            tokio::time::timeout(Duration::from_millis(10), gate.drain())
                .await
                .is_err()
        );
        drop(operation);
        let maintenance = gate.drain().await.unwrap();
        assert!(gate.enter().is_none());
        drop(maintenance);
        gate.reopen();
        assert!(gate.enter().is_some());
    }
}
