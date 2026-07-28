"""Sensor sync job queue persistence for the scheduler repository."""

from .admission import _SensorSyncJobAdmissionMixin
from .contracts import SensorSyncEnqueueResult
from .queries import _SensorSyncJobQueriesMixin
from .settlement import _SensorSyncJobSettlementMixin


class SensorSyncJobRepositoryMixin(
    _SensorSyncJobAdmissionMixin,
    _SensorSyncJobQueriesMixin,
    _SensorSyncJobSettlementMixin,
):
    """Queue, claim, and complete sensor sync jobs."""


__all__ = [
    "SensorSyncEnqueueResult",
    "SensorSyncJobRepositoryMixin",
]
