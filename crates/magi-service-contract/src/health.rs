//! Responsiveness accounting shared by process-external service owners.

use crate::lifecycle::SupervisionPolicy;
use std::time::{Duration, Instant};

#[derive(Default)]
pub struct ServiceHealth {
    last_probe: Option<Instant>,
    missed: u32,
}

impl ServiceHealth {
    pub fn due(&mut self, now: Instant, policy: &SupervisionPolicy) -> bool {
        if let Some(last) = self.last_probe {
            let gap = now.duration_since(last);
            if gap < Duration::from_secs(policy.probe_interval_secs) {
                return false;
            }
            // Never turn a suspended owner into a burst of overdue failures.
            if gap
                > Duration::from_secs(2 * (policy.probe_interval_secs + policy.probe_timeout_secs))
            {
                self.missed = 0;
            }
        }
        self.last_probe = Some(now);
        true
    }

    pub fn record(&mut self, responsive: bool) {
        self.missed = if responsive {
            0
        } else {
            self.missed.saturating_add(1)
        };
    }

    pub fn failed(&self, policy: &SupervisionPolicy) -> bool {
        self.missed >= policy.missed_probes
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn requires_consecutive_failures_and_discards_suspend_gaps() {
        let policy = SupervisionPolicy::default();
        let mut health = ServiceHealth::default();
        let mut now = Instant::now();
        for _ in 0..2 {
            assert!(health.due(now, &policy));
            health.record(false);
            assert!(!health.failed(&policy));
            now += Duration::from_secs(10);
        }
        health.record(true);
        assert!(!health.failed(&policy));
        for _ in 0..3 {
            health.record(false);
        }
        assert!(health.failed(&policy));
        now += Duration::from_secs(120);
        assert!(health.due(now, &policy));
        health.record(false);
        assert!(!health.failed(&policy));
        assert!(!health.due(now, &policy));
    }
}
