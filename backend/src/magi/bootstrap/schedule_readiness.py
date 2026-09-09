"""Bind scheduled target execution to its owning runtime capability."""

from ..core.container import get_container
from ..scheduler.contracts import ScheduledTargetType

_TARGET_MODULES = {
    ScheduledTargetType.SOURCE_SYNC: "runtime_source_sync_executor",
    ScheduledTargetType.MEMORY_L1_MAINTENANCE: "runtime_l1_maintenance_scheduler",
    ScheduledTargetType.MEMORY_L2_MAINTENANCE: "runtime_l2_maintenance_scheduler",
    ScheduledTargetType.MEMORY_L2_CONSOLIDATE: "runtime_l2_consolidation_scheduler",
    ScheduledTargetType.MEMORY_L2_DERIVE: "runtime_l2_derive_scheduler",
    ScheduledTargetType.MEMORY_L3_SUMMARY: "runtime_l3_summary_scheduler",
    ScheduledTargetType.MEMORY_L3_MAINTENANCE: "runtime_l3_maintenance_scheduler",
    ScheduledTargetType.MEMORY_L4_MAINTENANCE: "runtime_l4_maintenance_scheduler",
    ScheduledTargetType.USER_AGENT_TASK: "runtime_agent_schedule_registration",
    ScheduledTargetType.OUTREACH_OUTBOX_DRAIN: "runtime_outreach",
    ScheduledTargetType.RUNTIME_OPERATIONAL_GC: "runtime_operational_gc_scheduler",
    ScheduledTargetType.BACKGROUND_TASK_RETENTION: "runtime_agent_core",
    **{target: "runtime_timeline_schedulers" for target in (
        ScheduledTargetType.TIMELINE_DIARY_NARRATIVE, ScheduledTargetType.TIMELINE_STANDOUT_RESCORE,
        ScheduledTargetType.TIMELINE_MOOD_AGGREGATE, ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET,
        ScheduledTargetType.LOCATION_IPGEO_POLL, ScheduledTargetType.LOCATION_WIFI_POLL,
    )},
}


def schedule_target_ready(target: ScheduledTargetType) -> bool:
    """Fail closed until the contributor and its dependency graph are ready."""
    owner = get_container().runtime_orchestrator()
    module = _TARGET_MODULES.get(target)
    return module is not None and hasattr(owner, "is_ready") and owner.is_ready(module)
