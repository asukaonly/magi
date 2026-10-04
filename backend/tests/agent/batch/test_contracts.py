from magi.agent.batch.contracts import (
    BatchItemStatus,
    TERMINAL_ITEM_STATUSES,
)


def test_item_status_terminal_set():
    assert BatchItemStatus.DONE in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.FAILED in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.SKIPPED in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.PENDING not in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.NEEDS_REVIEW not in TERMINAL_ITEM_STATUSES
