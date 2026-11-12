"""Portable persistence values and deterministic row normalization."""

from enum import IntEnum


FACT_EVENTS_TABLE = "fact_events"


L1_EVENT_EMBEDDING_STATE_TABLE = "l1_event_embedding_state"


EMBEDDING_PROFILES_TABLE = "embedding_profiles"


EVENT_CHUNKS_TABLE = "l1_event_chunks"


EMBEDDING_TEXT_BUILDER_VERSION = "l1_content_v2"


EMBEDDING_STATUS_PENDING = "pending"


EMBEDDING_STATUS_READY = "ready"


EMBEDDING_STATUS_FAILED = "failed"


EMBEDDING_STATUS_SKIPPED = "skipped"


EMBEDDING_STATUS_DISABLED = "disabled"


class EmbeddingStatus(IntEnum):
    DISABLED = 1
    PENDING = 2
    READY = 3
    FAILED = 4
    SKIPPED = 5


_EMBEDDING_STATUS_LABELS = {
    EmbeddingStatus.DISABLED: EMBEDDING_STATUS_DISABLED,
    EmbeddingStatus.PENDING: EMBEDDING_STATUS_PENDING,
    EmbeddingStatus.READY: EMBEDDING_STATUS_READY,
    EmbeddingStatus.FAILED: EMBEDDING_STATUS_FAILED,
    EmbeddingStatus.SKIPPED: EMBEDDING_STATUS_SKIPPED,
}


_EMBEDDING_STATUS_BY_LABEL = {label: status for status, label in _EMBEDDING_STATUS_LABELS.items()}


def embedding_status_code(value: int | str | EmbeddingStatus | None) -> int:
    if value is None:
        return int(EmbeddingStatus.DISABLED)
    if isinstance(value, EmbeddingStatus):
        return int(value)
    if isinstance(value, int):
        return int(EmbeddingStatus(value))
    normalized = str(value).strip().lower()
    return int(_EMBEDDING_STATUS_BY_LABEL.get(normalized, EmbeddingStatus.DISABLED))


def embedding_status_label(value: int | str | EmbeddingStatus | None) -> str:
    return _EMBEDDING_STATUS_LABELS[EmbeddingStatus(embedding_status_code(value))]
