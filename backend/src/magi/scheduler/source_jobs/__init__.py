"""Source sync job queue persistence for the scheduler repository."""

from .admission import _SourceSyncJobAdmissionMixin
from .contracts import SourceSyncEnqueueResult, SourceSyncSuccessSettlement
from .queries import _SourceSyncJobQueriesMixin
from .settlement import _SourceSyncJobSettlementMixin


class SourceSyncJobRepositoryMixin(
    _SourceSyncJobAdmissionMixin,
    _SourceSyncJobQueriesMixin,
    _SourceSyncJobSettlementMixin,
):
    """Queue, claim, and complete source sync jobs."""


__all__ = [
    "SourceSyncEnqueueResult",
    "SourceSyncJobRepositoryMixin",
    "SourceSyncSuccessSettlement",
]
