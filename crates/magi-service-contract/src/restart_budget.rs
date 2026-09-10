use std::time::{Duration, Instant};

/// Count failures between sustained healthy periods, never across the service lifetime.
#[derive(Default)]
pub struct RestartBudget {
    pub attempts: u32,
    healthy_since: Option<Instant>,
}

impl RestartBudget {
    pub fn healthy(&mut self, now: Instant, stable_for: Duration) {
        let since = self.healthy_since.get_or_insert(now);
        if now.duration_since(*since) >= stable_for {
            self.attempts = 0;
        }
    }

    pub fn interrupted(&mut self) {
        self.healthy_since = None;
    }

    pub fn reset(&mut self) {
        *self = Self::default();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_sustained_health_restores_the_budget() {
        let now = Instant::now();
        let stable = Duration::from_secs(60);
        let mut budget = RestartBudget {
            attempts: 3,
            healthy_since: None,
        };
        budget.healthy(now, stable);
        budget.healthy(now + Duration::from_secs(59), stable);
        assert_eq!(budget.attempts, 3);
        budget.interrupted();
        budget.healthy(now + stable, stable);
        assert_eq!(budget.attempts, 3);
        budget.healthy(now + stable * 2, stable);
        assert_eq!(budget.attempts, 0);
    }
}
