//! Process supervision policy and diagnostics shared by lifecycle owners.

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct SupervisionPolicy {
    pub probe_interval_secs: u64,
    pub probe_timeout_secs: u64,
    pub missed_probes: u32,
    pub stable_after_secs: u64,
    pub cooldown_secs: u64,
}

impl Default for SupervisionPolicy {
    fn default() -> Self {
        Self {
            probe_interval_secs: 10,
            probe_timeout_secs: 5,
            missed_probes: 3,
            stable_after_secs: 60,
            cooldown_secs: 60,
        }
    }
}

impl SupervisionPolicy {
    pub fn validate(&self) -> Result<(), String> {
        if !(1..=60).contains(&self.probe_interval_secs)
            || !(1..=30).contains(&self.probe_timeout_secs)
            || !(2..=10).contains(&self.missed_probes)
            || !(1..=3600).contains(&self.stable_after_secs)
            || !(1..=3600).contains(&self.cooldown_secs)
        {
            return Err("Supervision limits are out of range".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SupervisorPhase {
    #[default]
    Starting,
    Ready,
    Unresponsive,
    Backoff,
    Cooldown,
    Failed,
    Stopping,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct SupervisorStatus {
    pub phase: SupervisorPhase,
    pub restart_count: u32,
    pub last_error: Option<String>,
    pub next_retry_at_ms: Option<u64>,
}
