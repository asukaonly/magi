"""Host-owned preview and lifecycle routes for one-shot history imports."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Response, status
from pydantic import BaseModel, Field

from ....memory.history_imports.markdown_parser import DOCUMENT_AUTHOR
from ....memory.history_imports.service import (
    HistoryImportNotFoundError,
    HistoryImportValidationError,
)
from ....memory.provider import get_history_import_service
from .router import memory_router


class MarkdownHistoryPreviewBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=50)


class HistoryImportConfirmBody(BaseModel):
    self_participants: list[str] = Field(default_factory=list, max_length=20)
    confirm_personal_writing: bool = False


class HistoryImportParticipantResponse(BaseModel):
    name: str
    is_document_author: bool
    message_count: int
    meaningful_count: int
    sample: str


class HistoryImportRecordPreviewResponse(BaseModel):
    source_name: str
    session_id: str
    session_seq: int
    speaker_name: str
    is_document_author: bool
    content: str
    event_at: float
    timestamp_confidence: str


class HistoryImportJobResponse(BaseModel):
    job_id: str
    source_type: str
    source_files: list[str]
    detected_kind: str
    status: str
    total_records: int
    meaningful_records: int
    quick_target_records: int
    quick_max_records: int
    quick_imported_count: int
    imported_count: int
    projected_count: int
    self_participants: list[str]
    warnings: list[str]
    quick_ready: bool
    error_code: str | None
    participants: list[HistoryImportParticipantResponse]
    preview_records: list[HistoryImportRecordPreviewResponse]


def _resolve_history_import_service() -> Any:
    try:
        return get_history_import_service()
    except RuntimeError:
        return None


def _response(job: Any) -> HistoryImportJobResponse:
    return HistoryImportJobResponse(
        job_id=job.job_id,
        source_type=job.source_type,
        source_files=list(job.source_files),
        detected_kind=job.detected_kind,
        status=job.status,
        total_records=job.total_records,
        meaningful_records=job.meaningful_records,
        quick_target_records=job.quick_target_records,
        quick_max_records=job.quick_max_records,
        quick_imported_count=job.quick_imported_count,
        imported_count=job.imported_count,
        projected_count=job.projected_count,
        self_participants=list(job.self_participants),
        warnings=list(job.warnings),
        quick_ready=job.quick_ready,
        error_code=job.error_text,
        participants=[
            HistoryImportParticipantResponse(
                name=participant.name,
                is_document_author=participant.name == DOCUMENT_AUTHOR,
                message_count=participant.message_count,
                meaningful_count=participant.meaningful_count,
                sample=participant.sample,
            )
            for participant in job.participants
        ],
        preview_records=[
            HistoryImportRecordPreviewResponse(
                source_name=record.source_name,
                session_id=record.session_id,
                session_seq=record.session_seq,
                speaker_name=record.speaker_name,
                is_document_author=record.speaker_name == DOCUMENT_AUTHOR,
                content=record.content,
                event_at=record.event_at,
                timestamp_confidence=record.timestamp_confidence,
            )
            for record in job.preview_records
        ],
    )


def _require_service() -> Any:
    service = _resolve_history_import_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="history_import_unavailable",
        )
    return service


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, HistoryImportNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.reason,
        ) from exc
    if isinstance(exc, HistoryImportValidationError):
        conflict_reasons = {
            "self_participant_locked_after_import",
            "memory_cleared_during_import",
        }
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if exc.reason in conflict_reasons
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=exc.reason,
        ) from exc
    raise exc


@memory_router.post(
    "/history-imports/markdown/preview",
    response_model=HistoryImportJobResponse,
)
async def preview_markdown_history(
    body: MarkdownHistoryPreviewBody,
) -> HistoryImportJobResponse:
    try:
        job = await _require_service().preview_markdown_paths(body.paths)
    except Exception as exc:
        _raise_service_error(exc)
        raise
    return _response(job)


@memory_router.get(
    "/history-imports/{job_id}",
    response_model=HistoryImportJobResponse,
)
async def get_history_import(job_id: str) -> HistoryImportJobResponse:
    try:
        job = await _require_service().get_job(job_id)
    except Exception as exc:
        _raise_service_error(exc)
        raise
    return _response(job)


@memory_router.post(
    "/history-imports/{job_id}/confirm",
    response_model=HistoryImportJobResponse,
)
async def confirm_history_import(
    job_id: str,
    body: HistoryImportConfirmBody,
) -> HistoryImportJobResponse:
    try:
        job = await _require_service().confirm(
            job_id=job_id,
            self_participants=body.self_participants,
            confirm_personal_writing=body.confirm_personal_writing,
        )
    except Exception as exc:
        _raise_service_error(exc)
        raise
    return _response(job)


@memory_router.post(
    "/history-imports/{job_id}/resume",
    response_model=HistoryImportJobResponse,
)
async def resume_history_import(job_id: str) -> HistoryImportJobResponse:
    try:
        job = await _require_service().resume(job_id)
    except Exception as exc:
        _raise_service_error(exc)
        raise
    return _response(job)


@memory_router.delete(
    "/history-imports/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_history_import(job_id: str) -> Response:
    try:
        await _require_service().delete(job_id)
    except Exception as exc:
        _raise_service_error(exc)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = [
    "HistoryImportConfirmBody",
    "HistoryImportJobResponse",
    "HistoryImportParticipantResponse",
    "HistoryImportRecordPreviewResponse",
    "MarkdownHistoryPreviewBody",
    "confirm_history_import",
    "delete_history_import",
    "get_history_import",
    "preview_markdown_history",
    "resume_history_import",
]
