"""Host-owned preview and lifecycle routes for one-shot history imports."""

from __future__ import annotations

import re
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
    confirm_personal_writing: bool = False
    included_source_ids: list[str] = Field(default_factory=list, max_length=500)
    self_participant_ids: list[str] = Field(default_factory=list, max_length=20)


class HistoryImportSelectionBody(BaseModel):
    included_source_ids: list[str] = Field(default_factory=list, max_length=500)


class HistoryImportParticipantResponse(BaseModel):
    participant_id: str
    display_name: str
    is_document_author: bool
    message_count: int
    meaningful_count: int
    sample: str


class HistoryImportRecordPreviewResponse(BaseModel):
    source_id: str
    source_name: str
    session_id: str
    session_seq: int
    speaker_id: str
    speaker_name: str
    is_document_author: bool
    content: str
    event_at: float
    timestamp_confidence: str


class HistoryImportSourceSummaryResponse(BaseModel):
    source_id: str
    source_name: str
    detected_kind: str
    record_count: int
    meaningful_count: int
    first_event_at: float
    last_event_at: float
    timestamp_confidence: str
    sample: str
    included: bool


class HistoryImportSourcePreviewResponse(BaseModel):
    source_id: str
    source_name: str
    detected_kind: str
    records: list[HistoryImportRecordPreviewResponse]
    truncated: bool


class HistoryImportWarningSummaryResponse(BaseModel):
    total_count: int
    codes: list[str]
    truncated: bool


class HistoryImportJobResponse(BaseModel):
    job_id: str
    source_type: str
    source_ids: list[str]
    included_source_ids: list[str]
    detected_kind: str
    status: str
    total_records: int
    meaningful_records: int
    quick_target_records: int
    quick_max_records: int
    quick_imported_count: int
    imported_count: int
    projected_count: int
    self_participant_ids: list[str]
    importer_plugin_id: str | None
    importer_id: str | None
    warning_summary: HistoryImportWarningSummaryResponse
    quick_ready: bool
    error_code: str | None
    created_at: float
    updated_at: float
    participants: list[HistoryImportParticipantResponse]
    sources: list[HistoryImportSourceSummaryResponse]
    preview_records: list[HistoryImportRecordPreviewResponse]


class HistoryImporterResponse(BaseModel):
    plugin_id: str
    importer_id: str
    display_name: str
    display_name_i18n: dict[str, str]
    description: str
    description_i18n: dict[str, str]
    accepted_extensions: list[str]
    participant_identity_scope: str
    export_help_url: str | None


class HistoryImporterPreviewBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=10)


def _resolve_history_import_service() -> Any:
    try:
        return get_history_import_service()
    except RuntimeError:
        return None


def _response(job: Any) -> HistoryImportJobResponse:
    return HistoryImportJobResponse(
        job_id=job.job_id,
        source_type=job.source_type,
        source_ids=list(job.source_ids),
        included_source_ids=list(job.included_source_ids),
        detected_kind=job.detected_kind,
        status=job.status,
        total_records=job.total_records,
        meaningful_records=job.meaningful_records,
        quick_target_records=job.quick_target_records,
        quick_max_records=job.quick_max_records,
        quick_imported_count=job.quick_imported_count,
        imported_count=job.imported_count,
        projected_count=job.projected_count,
        self_participant_ids=list(job.self_participant_ids),
        importer_plugin_id=job.importer_plugin_id,
        importer_id=job.importer_id,
        warning_summary=_warning_summary(job.warnings),
        quick_ready=job.quick_ready,
        error_code=job.error_text,
        created_at=job.created_at,
        updated_at=job.updated_at,
        participants=[
            HistoryImportParticipantResponse(
                participant_id=participant.participant_id,
                display_name=participant.display_name,
                is_document_author=participant.participant_id == DOCUMENT_AUTHOR,
                message_count=participant.message_count,
                meaningful_count=participant.meaningful_count,
                sample=participant.sample,
            )
            for participant in job.participants
        ],
        sources=[
            HistoryImportSourceSummaryResponse(
                source_id=source.source_id,
                source_name=source.source_name,
                detected_kind=source.detected_kind,
                record_count=source.record_count,
                meaningful_count=source.meaningful_count,
                first_event_at=source.first_event_at,
                last_event_at=source.last_event_at,
                timestamp_confidence=source.timestamp_confidence,
                sample=source.sample,
                included=source.included,
            )
            for source in job.sources
        ],
        preview_records=[
            HistoryImportRecordPreviewResponse(
                source_id=record.source_id,
                source_name=record.source_name,
                session_id=record.session_id,
                session_seq=record.session_seq,
                speaker_id=record.speaker_id,
                speaker_name=record.speaker_name,
                is_document_author=record.speaker_id == DOCUMENT_AUTHOR,
                content=record.content,
                event_at=record.event_at,
                timestamp_confidence=record.timestamp_confidence,
            )
            for record in job.preview_records
        ],
    )


def _warning_summary(warnings: list[str]) -> HistoryImportWarningSummaryResponse:
    truncation_prefix = "history_import_warnings_truncated:"
    truncation_markers = [warning for warning in warnings if warning.startswith(truncation_prefix)]
    truncated = bool(truncation_markers)
    visible_warnings = [
        warning for warning in warnings if not warning.startswith(truncation_prefix)
    ]
    total_count = len(visible_warnings)
    if truncation_markers:
        try:
            total_count = max(
                total_count,
                int(truncation_markers[-1].removeprefix(truncation_prefix)),
            )
        except ValueError:
            pass
    codes: list[str] = []
    for warning in visible_warnings:
        candidate = str(warning).partition(":")[0].strip().casefold()
        code = candidate if re.fullmatch(r"[a-z0-9_]{1,64}", candidate) else "unknown"
        if code not in codes:
            codes.append(code)
        if len(codes) >= 20:
            truncated = True
            break
    return HistoryImportWarningSummaryResponse(
        total_count=total_count,
        codes=codes,
        truncated=truncated,
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
            "history_import_confirmation_conflict",
            "history_import_scope_conflict",
            "history_import_speaker_role_conflict",
            "history_importer_non_append_update",
            "self_participant_locked_after_import",
            "history_import_selection_locked",
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
    "/history-imports/importers",
    response_model=list[HistoryImporterResponse],
)
async def list_history_importers() -> list[HistoryImporterResponse]:
    return [
        HistoryImporterResponse(
            plugin_id=item.plugin_id,
            importer_id=item.importer_id,
            display_name=item.spec.display_name,
            display_name_i18n=dict(item.spec.display_name_i18n),
            description=item.spec.description,
            description_i18n=dict(item.spec.description_i18n),
            accepted_extensions=list(item.spec.accepted_extensions),
            participant_identity_scope=item.spec.participant_identity_scope,
            export_help_url=item.spec.export_help_url,
        )
        for item in _require_service().list_importers()
    ]


@memory_router.post(
    "/history-imports/importers/{plugin_id}/{importer_id}/preview",
    response_model=HistoryImportJobResponse,
)
async def preview_importer_history(
    plugin_id: str,
    importer_id: str,
    body: HistoryImporterPreviewBody,
) -> HistoryImportJobResponse:
    try:
        job = await _require_service().preview_importer_paths(
            plugin_id=plugin_id,
            importer_id=importer_id,
            paths=body.paths,
        )
    except Exception as exc:
        _raise_service_error(exc)
        raise
    return _response(job)


@memory_router.get(
    "/history-imports",
    response_model=list[HistoryImportJobResponse],
)
async def list_history_imports() -> list[HistoryImportJobResponse]:
    jobs = await _require_service().list_jobs()
    return [_response(job) for job in jobs]


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


@memory_router.get(
    "/history-imports/{job_id}/source-preview",
    response_model=HistoryImportSourcePreviewResponse,
)
async def get_history_import_source_preview(
    job_id: str,
    source_id: str,
) -> HistoryImportSourcePreviewResponse:
    try:
        preview = await _require_service().get_source_preview(
            job_id=job_id,
            source_id=source_id,
        )
    except Exception as exc:
        _raise_service_error(exc)
        raise
    return HistoryImportSourcePreviewResponse(
        source_id=preview.source_id,
        source_name=preview.source_name,
        detected_kind=preview.detected_kind,
        records=[
            HistoryImportRecordPreviewResponse(
                source_id=record.source_id,
                source_name=record.source_name,
                session_id=record.session_id,
                session_seq=record.session_seq,
                speaker_id=record.speaker_id,
                speaker_name=record.speaker_name,
                is_document_author=record.speaker_id == DOCUMENT_AUTHOR,
                content=record.content,
                event_at=record.event_at,
                timestamp_confidence=record.timestamp_confidence,
            )
            for record in preview.records
        ],
        truncated=preview.truncated,
    )


@memory_router.patch(
    "/history-imports/{job_id}/selection",
    response_model=HistoryImportJobResponse,
)
async def update_history_import_selection(
    job_id: str,
    body: HistoryImportSelectionBody,
) -> HistoryImportJobResponse:
    try:
        job = await _require_service().update_selection(
            job_id=job_id,
            included_source_ids=body.included_source_ids,
        )
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
            confirm_personal_writing=body.confirm_personal_writing,
            included_source_ids=body.included_source_ids,
            self_participant_ids=body.self_participant_ids,
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
    "HistoryImportSelectionBody",
    "HistoryImportSourcePreviewResponse",
    "HistoryImportSourceSummaryResponse",
    "HistoryImportWarningSummaryResponse",
    "MarkdownHistoryPreviewBody",
    "confirm_history_import",
    "delete_history_import",
    "get_history_import",
    "get_history_import_source_preview",
    "list_history_imports",
    "preview_markdown_history",
    "resume_history_import",
    "update_history_import_selection",
]
