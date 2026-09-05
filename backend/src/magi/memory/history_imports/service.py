"""Host-owned Markdown preview, quick context, and ordered background import."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
from functools import partial
import hashlib
import inspect
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from magi_plugin_sdk import HistoryImportParseResult
from magi_plugin_sdk.history_imports import (
    MAX_HISTORY_IMPORT_CONTENT_LENGTH,
    MAX_HISTORY_IMPORT_RECORDS_PER_SOURCE,
    MAX_HISTORY_IMPORT_SOURCES,
    MAX_HISTORY_IMPORT_SOURCE_WARNINGS,
    MAX_HISTORY_IMPORT_WARNING_LENGTH,
    MAX_HISTORY_IMPORT_WARNINGS,
)
from pydantic import BaseModel, ValidationError

from ...core.logger import get_logger
from ...core.operation_barrier import AsyncOperationBarrier
from ...utils.calendar_timezone import local_calendar_timezone_id, with_calendar_timezone
from ...identity import CANONICAL_LOCAL_USER
from ..event_contracts import (
    AuthorType,
    ContentType,
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from .markdown_parser import DOCUMENT_AUTHOR, parse_markdown
from .models import (
    HistoryImportAppendResult,
    HistoryImportJob,
    HistoryImportRecord,
    HistoryImportSourcePreview,
    ParsedHistorySource,
)
from ...plugins.history_importers import HistoryImporterRegistry, RegisteredHistoryImporter
from .store import HistoryImportStore

logger = get_logger(__name__)

MAX_MARKDOWN_FILES = 50
MAX_MARKDOWN_FILE_BYTES = 5 * 1024 * 1024
MAX_MARKDOWN_TOTAL_BYTES = 25 * 1024 * 1024
QUICK_TARGET_RECORDS = 200
QUICK_MAX_RECORDS = 500
RAW_BATCH_SIZE = 100
PROJECTION_BATCH_SIZE = 40
SOURCE_PREVIEW_MAX_RECORDS = 200
SOURCE_PREVIEW_MAX_CHARS = 48_000
MAX_IMPORTER_TOTAL_RECORDS = 100_000
MAX_IMPORTER_TOTAL_CONTENT_CHARS = 50_000_000
MAX_STORED_IMPORT_WARNINGS = 200
IMPORTER_PARSE_TIMEOUT_SECONDS = 60.0
IMPORTER_PARSE_SHUTDOWN_GRACE_SECONDS = 1.0
MAX_CONCURRENT_IMPORTER_PARSERS = 2
HISTORY_IMPORT_SOURCE = "history_import"
MARKDOWN_IMPORT_POLICY_VERSION = b"personal-writing-v1"


class HistoryImportError(RuntimeError):
    """Base error carrying a stable reader-facing reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HistoryImportNotFoundError(HistoryImportError):
    def __init__(self) -> None:
        super().__init__("history_import_not_found")


class HistoryImportValidationError(HistoryImportError):
    pass


class _HistoryImportEpochChanged(RuntimeError):
    pass


class _HistoryImporterOutputInvalid(RuntimeError):
    pass


class _HistoryImporterOutputTooLarge(_HistoryImporterOutputInvalid):
    pass


class HistoryImportService:
    """Create previews and advance imports without letting adapters write memory."""

    def __init__(
        self,
        *,
        store: HistoryImportStore,
        memory: Any,
        importer_registry: HistoryImporterRegistry | None = None,
        connection_name_resolver: Callable[[str], str | None] | None = None,
        consolidation_request: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._consolidation_request = consolidation_request
        self._store = store
        self._memory = memory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._quick_tasks: dict[str, asyncio.Task[None]] = {}
        self._confirmation_payloads: dict[
            str,
            tuple[bool, tuple[str, ...] | None, tuple[str, ...]],
        ] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._deletion_lock = asyncio.Lock()
        self._operation_barrier = AsyncOperationBarrier()
        self._importer_registry = importer_registry or HistoryImporterRegistry()
        self._connection_name_resolver = connection_name_resolver
        self._importer_parse_slots = asyncio.BoundedSemaphore(MAX_CONCURRENT_IMPORTER_PARSERS)
        self._importer_parse_tasks: set[asyncio.Task[Any]] = set()
        self._importer_lifecycle_generation = 0
        self._accepting_importer_previews = True

    def list_importers(self) -> list[RegisteredHistoryImporter]:
        """Return enabled importer contributions available to the host UI."""

        return [entry for entry in self._importer_registry.list() if entry.connection_id is not None]

    def connection_display_name(self, connection_id: str) -> str | None:
        """Return the host-owned account label for an enabled importer."""
        return self._connection_name_resolver(connection_id) if self._connection_name_resolver else None

    async def _invoke_history_importer(
        self,
        registered: RegisteredHistoryImporter,
        resolved_paths: list[Path],
        *,
        lifecycle_generation: int,
    ) -> Any:
        """Run one parser off-loop while retaining its slot until worker exit."""

        await self._importer_parse_slots.acquire()
        if (
            not self._accepting_importer_previews
            or lifecycle_generation != self._importer_lifecycle_generation
        ):
            self._importer_parse_slots.release()
            raise HistoryImportValidationError("history_importer_not_available")
        try:
            task = asyncio.create_task(
                asyncio.to_thread(
                    _run_history_importer_in_worker,
                    registered,
                    resolved_paths,
                ),
                name=f"history-import-parser:{registered.connection_id}:{registered.importer_id}",
            )
        except BaseException:
            self._importer_parse_slots.release()
            raise
        self._importer_parse_tasks.add(task)
        task.add_done_callback(self._finish_importer_parse_task)
        return await asyncio.shield(task)

    def _finish_importer_parse_task(self, task: asyncio.Task[Any]) -> None:
        """Release capacity only after the underlying thread has returned."""

        self._importer_parse_tasks.discard(task)
        self._importer_parse_slots.release()
        if not task.cancelled():
            task.exception()

    async def start(self) -> None:
        """Resume confirmed imports from their last durable boundary."""

        self._accepting_importer_previews = True
        async with self._operation():
            await self._log_integrity_audit(checkpoint="startup")
            quick_resumable_job_ids = await self._store.list_quick_resumable_job_ids()
            resumable_job_ids = await self._store.list_resumable_job_ids()
            logger.info(
                "History import service started",
                process_id=os.getpid(),
                quick_resumable_job_count=len(quick_resumable_job_ids),
                resumable_job_count=len(resumable_job_ids),
            )
            for job_id in quick_resumable_job_ids:
                self._start_quick(job_id)
            for job_id in resumable_job_ids:
                self._start_background(job_id)

    async def stop(self) -> None:
        self._accepting_importer_previews = False
        self._importer_lifecycle_generation += 1
        async with self._operation_barrier.exclusive():
            await self._cancel_background_tasks()
            await self._drain_importer_parse_tasks()
            self._locks.clear()

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Seal import work and drain background tasks before durable deletion."""

        async with self._operation_barrier.exclusive():
            await self._cancel_background_tasks()
            self._locks.clear()
            yield

    async def preview_markdown_paths(self, paths: list[str]) -> HistoryImportJob:
        """Parse selected files or folders and persist a safe preview."""

        async with self._operation():
            return await self._preview_markdown_paths(paths)

    async def _preview_markdown_paths(self, paths: list[str]) -> HistoryImportJob:
        """Persist one preview while the service operation boundary is held."""

        parsed_files, file_fingerprints, fingerprint, warnings = _parse_markdown_selection(paths)
        existing = await self._store.find_active_by_fingerprint(fingerprint)
        if existing is not None:
            return existing

        now = time.time()
        job_id = f"him_{uuid.uuid4().hex}"
        detected_kinds = {item.detected_kind for item in parsed_files}
        detected_kind = next(iter(detected_kinds)) if len(detected_kinds) == 1 else "mixed"
        records = _build_records(
            job_id=job_id,
            file_fingerprints=file_fingerprints,
            parsed_files=parsed_files,
            now=now,
        )
        job = HistoryImportJob(
            job_id=job_id,
            source_type="markdown",
            source_fingerprint=fingerprint,
            source_ids=[item.source_id for item in parsed_files],
            included_source_ids=[item.source_id for item in parsed_files],
            detected_kind=detected_kind,
            status="preview_ready",
            total_records=len(records),
            meaningful_records=sum(1 for record in records if record.meaningful),
            quick_target_records=QUICK_TARGET_RECORDS,
            quick_max_records=QUICK_MAX_RECORDS,
            quick_imported_count=0,
            imported_count=0,
            projected_count=0,
            self_participant_ids=[],
            warnings=warnings,
            quick_ready=False,
            created_at=now,
            updated_at=now,
        )
        return await self._store.create_preview(job=job, records=records)

    async def append_markdown_paths(
        self,
        *,
        job_id: str,
        paths: list[str],
    ) -> HistoryImportAppendResult:
        """Extend an unconfirmed Markdown preview without replacing its selection."""

        async with self._operation():
            lock = self._lock_for(job_id)
            async with lock:
                job = await self._get_job(job_id)
                if job.source_type != "markdown":
                    raise HistoryImportValidationError("history_import_append_type_mismatch")
                if self._scope_confirmed(job) or job.quick_ready or job.imported_count > 0:
                    raise HistoryImportValidationError("history_import_selection_locked")
                parsed_files, file_fingerprints, _fingerprint, warnings = _parse_markdown_selection(
                    paths
                )
                incoming_source_ids = {source.source_id for source in parsed_files}
                if len(set(job.source_ids).union(incoming_source_ids)) > MAX_MARKDOWN_FILES:
                    raise HistoryImportValidationError("markdown_too_many_files")
                now = time.time()
                records = _build_records(
                    job_id=job_id,
                    file_fingerprints=file_fingerprints,
                    parsed_files=parsed_files,
                    now=now,
                )
                try:
                    return await self._store.append_preview(
                        job_id=job_id,
                        records=records,
                        warnings=_bounded_import_warnings([*job.warnings, *warnings]),
                        allow_existing_source_updates=False,
                    )
                except KeyError as exc:
                    raise HistoryImportNotFoundError() from exc
                except ValueError as exc:
                    reason = str(exc)
                    if reason in {
                        "history_import_selection_locked",
                        "history_import_source_name_conflict",
                    }:
                        raise HistoryImportValidationError(reason) from exc
                    if reason == "history_import_source_identity_conflict":
                        raise HistoryImportValidationError(
                            "history_import_selection_changed"
                        ) from exc
                    raise

    async def preview_importer_paths(
        self,
        *,
        plugin_id: str,
        importer_id: str,
        connection_id: str,
        paths: list[str],
    ) -> HistoryImportJob:
        """Parse a declared platform export and persist a host-owned preview."""

        if not self._accepting_importer_previews:
            raise HistoryImportValidationError("history_importer_not_available")
        lifecycle_generation = self._importer_lifecycle_generation
        if not connection_id or not connection_id.strip():
            raise HistoryImportValidationError("history_importer_not_available")
        registered = self._importer_registry.get(plugin_id, importer_id, connection_id=connection_id)
        if registered is None:
            raise HistoryImportValidationError("history_importer_not_available")
        resolved_paths = _validate_importer_paths(paths, registered)
        expected_epoch = int(self._memory.memory_operation_epoch())
        try:
            initial_fingerprint = await asyncio.to_thread(
                _platform_import_fingerprint,
                registered,
                resolved_paths,
            )
            parsed = await asyncio.wait_for(
                self._invoke_history_importer(
                    registered,
                    resolved_paths,
                    lifecycle_generation=lifecycle_generation,
                ),
                timeout=IMPORTER_PARSE_TIMEOUT_SECONDS,
            )
            final_fingerprint = await asyncio.to_thread(
                _platform_import_fingerprint,
                registered,
                resolved_paths,
            )
        except TimeoutError as exc:
            logger.warning(
                "History importer parse timed out",
                plugin_id=plugin_id,
                importer_id=importer_id,
            )
            raise HistoryImportValidationError("history_importer_timeout") from exc
        except (ValidationError, _HistoryImporterOutputInvalid) as exc:
            logger.warning(
                "History importer returned invalid output",
                plugin_id=plugin_id,
                importer_id=importer_id,
                error_type=type(exc).__name__,
            )
            reason = "history_importer_invalid_output"
            if isinstance(exc, _HistoryImporterOutputTooLarge) or (
                isinstance(exc, ValidationError) and _validation_error_is_size_limit(exc)
            ):
                reason = "history_importer_output_too_large"
            raise HistoryImportValidationError(reason) from exc
        except OSError as exc:
            logger.warning(
                "History importer selection changed during preview",
                plugin_id=plugin_id,
                importer_id=importer_id,
                error_type=type(exc).__name__,
            )
            raise HistoryImportValidationError("history_import_selection_changed") from exc
        except HistoryImportValidationError:
            raise
        except Exception as exc:
            logger.warning(
                "History importer parse failed",
                plugin_id=plugin_id,
                importer_id=importer_id,
                error_type=type(exc).__name__,
            )
            raise HistoryImportValidationError("history_importer_parse_failed") from exc
        if final_fingerprint != initial_fingerprint:
            raise HistoryImportValidationError("history_import_selection_changed")

        async with self._operation():
            if (
                not self._accepting_importer_previews
                or lifecycle_generation != self._importer_lifecycle_generation
            ):
                raise HistoryImportValidationError("history_importer_not_available")
            current = self._importer_registry.get(plugin_id, importer_id, connection_id=connection_id)
            if current is not registered:
                raise HistoryImportValidationError("history_importer_not_available")
            if int(self._memory.memory_operation_epoch()) != expected_epoch:
                raise HistoryImportValidationError("memory_cleared_during_import")
            timezone_id = local_calendar_timezone_id()
            if timezone_id is None:
                raise HistoryImportValidationError("history_import_timezone_unavailable")
            parsed_sources = [
                ParsedHistorySource(
                    source_id=source.source_id,
                    source_name=source.source_name,
                    session_key=source.session_key,
                    detected_kind=source.detected_kind,
                    records=[
                        {
                            "message_key": record.message_key,
                            "parent_message_key": record.parent_message_key,
                            "speaker_id": _platform_participant_id(
                                registered=registered,
                                source_id=source.source_id,
                                raw_speaker_id=record.speaker_id,
                            ),
                            "speaker_name": record.speaker_name,
                            "content": record.content,
                            "event_at": record.occurred_at,
                            "timestamp_confidence": record.timestamp_confidence,
                            "timestamp_anchor_source": (
                                "source_timestamp"
                                if record.occurred_at is not None
                                else "source_order"
                            ),
                            "calendar_timezone_id": timezone_id,
                            "meaningful": _is_meaningful_imported_message(record.content),
                            "source_order": record.source_order,
                        }
                        for record in source.records
                    ],
                    warnings=list(source.warnings),
                )
                for source in parsed.sources
            ]
            try:
                await self._store.validate_platform_session_prefixes(
                    connection_id=connection_id,
                    importer_plugin_id=plugin_id,
                    importer_id=importer_id,
                    importer_format_version=registered.spec.format_version,
                    sources=parsed_sources,
                )
            except ValueError as exc:
                if str(exc) != "history_import_non_append_update":
                    raise
                raise HistoryImportValidationError("history_importer_non_append_update") from exc
            return await self._create_importer_preview(
                registered=registered,
                fingerprint=initial_fingerprint,
                parsed_sources=parsed_sources,
                warnings=list(parsed.warnings),
            )

    async def _create_importer_preview(
        self,
        *,
        registered: RegisteredHistoryImporter,
        fingerprint: str,
        parsed_sources: list[ParsedHistorySource],
        warnings: list[str],
    ) -> HistoryImportJob:
        if not parsed_sources:
            raise HistoryImportValidationError("history_importer_no_sources")
        source_ids = [source.source_id for source in parsed_sources]
        if len(source_ids) != len(set(source_ids)):
            raise HistoryImportValidationError("history_importer_duplicate_source_id")
        existing = await self._store.find_active_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        now = time.time()
        job_id = f"him_{uuid.uuid4().hex}"
        records = _build_records(
            job_id=job_id,
            file_fingerprints={},
            parsed_files=parsed_sources,
            now=now,
            importer_identity=(
                registered.connection_id,
                registered.plugin_id,
                registered.importer_id,
                registered.spec.format_version,
            ),
            missing_timestamp_anchor=0.0,
        )
        job = HistoryImportJob(
            job_id=job_id,
            source_type="platform_chat",
            source_fingerprint=fingerprint,
            source_ids=source_ids,
            included_source_ids=source_ids,
            detected_kind="chat",
            status="preview_ready",
            total_records=len(records),
            meaningful_records=sum(record.meaningful for record in records),
            quick_target_records=QUICK_TARGET_RECORDS,
            quick_max_records=QUICK_MAX_RECORDS,
            quick_imported_count=0,
            imported_count=0,
            projected_count=0,
            self_participant_ids=[],
            warnings=_bounded_import_warnings(
                [*warnings, *(warning for source in parsed_sources for warning in source.warnings)]
            ),
            quick_ready=False,
            created_at=now,
            updated_at=now,
            connection_id=registered.connection_id,
            importer_plugin_id=registered.plugin_id,
            importer_id=registered.importer_id,
            importer_format_version=registered.spec.format_version,
        )
        try:
            return await self._store.create_preview(job=job, records=records)
        except ValueError as exc:
            if str(exc) != "history_import_source_identity_conflict":
                raise
            logger.warning(
                "History importer reused an identity with different content",
                plugin_id=registered.plugin_id,
                importer_id=registered.importer_id,
                error_type=type(exc).__name__,
            )
            raise HistoryImportValidationError("history_importer_invalid_output") from exc

    async def get_job(self, job_id: str) -> HistoryImportJob:
        """Return preview details only while the job still needs confirmation."""

        async with self._operation():
            job = await self._get_job_progress(job_id)
            if job.status == "preview_ready":
                return await self._get_job(job_id)
            return job

    async def _get_job(self, job_id: str) -> HistoryImportJob:
        """Load one job with participant, source, and content preview details."""

        job = await self._store.get_job(job_id)
        if job is None or job.deleted_at is not None or job.status == "deleted":
            raise HistoryImportNotFoundError()
        return job

    async def _get_job_progress(self, job_id: str) -> HistoryImportJob:
        """Load lifecycle state without hydrating record-derived preview details."""

        job = await self._store.get_job_progress(job_id)
        if job is None:
            raise HistoryImportNotFoundError()
        return job

    async def list_jobs(self, *, limit: int = 20) -> list[HistoryImportJob]:
        """Return active imports for reader-facing progress and deletion."""

        async with self._operation():
            return await self._store.list_active_jobs(limit=limit)

    async def get_source_preview(
        self,
        *,
        job_id: str,
        source_id: str,
    ) -> HistoryImportSourcePreview:
        """Return a bounded preview for one file without changing its selection."""

        async with self._operation():
            return await self._get_source_preview(
                job_id=job_id,
                source_id=source_id,
            )

    async def _get_source_preview(
        self,
        *,
        job_id: str,
        source_id: str,
    ) -> HistoryImportSourcePreview:
        """Load one source preview while the service operation boundary is held."""

        job = await self._get_job(job_id)
        if source_id not in job.source_ids:
            raise HistoryImportValidationError("history_import_source_not_found")
        source = next(item for item in job.sources if item.source_id == source_id)
        loaded = await self._store.list_source_records(
            job_id=job_id,
            source_id=source_id,
            limit=SOURCE_PREVIEW_MAX_RECORDS + 1,
        )
        truncated = len(loaded) > SOURCE_PREVIEW_MAX_RECORDS
        remaining_chars = SOURCE_PREVIEW_MAX_CHARS
        records: list[HistoryImportRecord] = []
        for record in loaded[:SOURCE_PREVIEW_MAX_RECORDS]:
            if remaining_chars <= 0:
                truncated = True
                break
            content = record.content
            if len(content) > remaining_chars:
                content = content[:remaining_chars]
                truncated = True
            records.append(replace(record, content=content))
            remaining_chars -= len(content)
        return HistoryImportSourcePreview(
            source_id=source_id,
            source_name=source.source_name,
            detected_kind=source.detected_kind,
            records=records,
            truncated=truncated,
        )

    async def update_selection(
        self,
        *,
        job_id: str,
        included_source_ids: list[str],
    ) -> HistoryImportJob:
        """Persist the file subset selected in the preview."""

        async with self._operation():
            return await self._update_selection(
                job_id=job_id,
                included_source_ids=included_source_ids,
            )

    async def _update_selection(
        self,
        *,
        job_id: str,
        included_source_ids: list[str],
    ) -> HistoryImportJob:
        """Update selection while the service operation boundary is held."""

        lock = self._lock_for(job_id)
        async with lock:
            job = await self._get_job(job_id)
            if self._scope_confirmed(job) or job.quick_ready or job.imported_count > 0:
                raise HistoryImportValidationError("history_import_selection_locked")
            normalized = _validate_included_sources(
                job,
                included_source_ids,
                allow_empty=True,
            )
            try:
                return await self._store.update_selection(
                    job_id=job_id,
                    included_source_ids=normalized,
                )
            except ValueError as exc:
                if str(exc) == "history_import_selection_locked":
                    raise HistoryImportValidationError(str(exc)) from exc
                raise
            except KeyError as exc:
                raise HistoryImportNotFoundError() from exc

    async def confirm(
        self,
        *,
        job_id: str,
        confirm_personal_writing: bool,
        included_source_ids: list[str] | None = None,
        self_participant_ids: list[str] | None = None,
    ) -> HistoryImportJob:
        """Confirm authorship, prepare recent raw context, and continue in order."""

        task = self._start_confirmation(
            job_id=job_id,
            confirm_personal_writing=confirm_personal_writing,
            included_source_ids=included_source_ids,
            self_participant_ids=self_participant_ids,
        )
        await asyncio.shield(task)
        return await self.get_job(job_id)

    async def _confirm(
        self,
        *,
        job_id: str,
        confirm_personal_writing: bool,
        included_source_ids: list[str] | None = None,
        self_participant_ids: list[str] | None = None,
    ) -> HistoryImportJob:
        """Persist one confirmed scope while the operation boundary is held."""

        lock = self._lock_for(job_id)
        async with lock:
            job = await self._get_job(job_id)
            if job.deleted_at is not None or job.status == "deleted":
                raise HistoryImportNotFoundError()
            selected_files = _validate_included_sources(
                job,
                included_source_ids if included_source_ids is not None else job.included_source_ids,
            )
            participants = await self._store.list_participants_for_sources(
                job_id=job_id,
                included_source_ids=selected_files,
            )
            participant_ids = {item.participant_id for item in participants}
            selected_source_set = set(selected_files)
            selected_kinds = {
                source.detected_kind
                for source in job.sources
                if source.source_id in selected_source_set
            }
            if selected_kinds == {"document"}:
                if DOCUMENT_AUTHOR not in participant_ids:
                    raise HistoryImportValidationError("history_import_unsupported_source_kind")
                if not confirm_personal_writing:
                    raise HistoryImportValidationError("personal_writing_confirmation_required")
                selected = [DOCUMENT_AUTHOR]
            elif selected_kinds == {"chat"}:
                selected = list(dict.fromkeys(self_participant_ids or []))
                if not selected or any(item not in participant_ids for item in selected):
                    raise HistoryImportValidationError("history_import_self_participant_required")
            else:
                raise HistoryImportValidationError("history_import_unsupported_source_kind")
            logger.info(
                "History import confirmation started",
                process_id=os.getpid(),
                job_id=job_id,
                selected_file_count=len(selected_files),
                total_record_count=job.total_records,
                imported_count=job.imported_count,
                quick_ready=job.quick_ready,
            )
            try:
                await self._store.set_scope(
                    job_id=job_id,
                    self_participant_ids=selected,
                    included_source_ids=selected_files,
                )
            except ValueError as exc:
                reason = str(exc)
                if reason == "history_import_non_append_update":
                    raise HistoryImportValidationError(
                        "history_importer_non_append_update"
                    ) from exc
                if reason in {
                    "history_import_scope_conflict",
                    "history_import_speaker_role_conflict",
                }:
                    raise HistoryImportValidationError(reason) from exc
                raise
            except KeyError as exc:
                raise HistoryImportNotFoundError() from exc
            return await self._get_job_progress(job_id)

    async def get_first_contact_snippet(self) -> str | None:
        """Return bounded user-authored excerpts from the latest confirmed import."""

        async with self._operation():
            return await self._get_first_contact_snippet()

    async def _get_first_contact_snippet(self) -> str | None:
        """Read first-contact excerpts while the service operation boundary is held."""

        records = await self._store.list_first_contact_records(limit=16)
        if not records:
            return None
        selected: list[HistoryImportRecord] = []
        seen_sources: set[str] = set()
        for record in records:
            if record.source_id in seen_sources:
                continue
            selected.append(record)
            seen_sources.add(record.source_id)
            if len(selected) >= 4:
                break
        if len(selected) < 4:
            selected_ids = {record.job_record_id for record in selected}
            for record in records:
                if record.job_record_id in selected_ids:
                    continue
                selected.append(record)
                if len(selected) >= 4:
                    break
        lines: list[str] = []
        for record in selected:
            compact = re.sub(r"\s+", " ", record.content).strip()
            if compact:
                compact = compact.replace("<", "‹").replace(">", "›")
                lines.append(f"- {compact[:320]}")
        return "\n".join(lines) or None

    async def resume(self, job_id: str) -> HistoryImportJob:
        async with self._operation():
            return await self._resume(job_id)

    async def _resume(self, job_id: str) -> HistoryImportJob:
        async with self._lock_for(job_id):
            job = await self._get_job_progress(job_id)
            if job.status == "deleted":
                return job
            if not job.quick_ready:
                if not self._scope_confirmed(job):
                    raise HistoryImportValidationError("history_import_not_confirmed")
                await self._store.mark_running(job_id=job_id)
                self._start_quick(job_id)
                return await self._get_job_progress(job_id)
            reset_count = await self._store.reset_skipped_projections(job_id=job_id)
            if job.status == "completed" and reset_count == 0:
                return job
            await self._store.mark_running(job_id=job_id)
            self._start_background(job_id)
            return await self._get_job_progress(job_id)

    async def delete(self, job_id: str) -> None:
        async with self._operation():
            await self._delete(job_id)

    async def _delete(self, job_id: str) -> None:
        tasks = [
            task
            for task in (
                self._quick_tasks.pop(job_id, None),
                self._tasks.pop(job_id, None),
            )
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._deletion_lock:
            async with self._lock_for(job_id):
                job = await self._get_job_progress(job_id)
                if job.status == "deleted":
                    return
                event_ids = await self._store.list_unreferenced_event_ids_for_delete(job_id=job_id)
                logger.info(
                    "History import deletion started",
                    process_id=os.getpid(),
                    job_id=job_id,
                    unreferenced_event_count=len(event_ids),
                )
                if event_ids:
                    await self._memory.forget_reimportable_source_events(
                        event_ids,
                        reason="history_import_deleted",
                    )
                await self._store.mark_deleted(job_id=job_id)
                await self._log_integrity_audit(checkpoint="deleted")

    def _start_confirmation(
        self,
        *,
        job_id: str,
        confirm_personal_writing: bool,
        included_source_ids: list[str] | None,
        self_participant_ids: list[str] | None,
    ) -> asyncio.Task[None]:
        request_payload = _confirmation_payload(
            confirm_personal_writing=confirm_personal_writing,
            included_source_ids=included_source_ids,
            self_participant_ids=self_participant_ids,
        )
        existing = self._quick_tasks.get(job_id)
        if existing is not None and not existing.done():
            if self._confirmation_payloads.get(job_id) != request_payload:
                raise HistoryImportValidationError("history_import_confirmation_conflict")
            return existing
        task = asyncio.create_task(
            self._confirm_and_run_quick(
                job_id=job_id,
                confirm_personal_writing=confirm_personal_writing,
                included_source_ids=included_source_ids,
                self_participant_ids=self_participant_ids,
            ),
            name=f"history-import-confirm:{job_id}",
        )
        self._quick_tasks[job_id] = task
        self._confirmation_payloads[job_id] = request_payload
        task.add_done_callback(partial(self._quick_task_finished, job_id))
        return task

    async def _confirm_and_run_quick(
        self,
        *,
        job_id: str,
        confirm_personal_writing: bool,
        included_source_ids: list[str] | None,
        self_participant_ids: list[str] | None,
    ) -> None:
        async with self._operation():
            await self._confirm(
                job_id=job_id,
                confirm_personal_writing=confirm_personal_writing,
                included_source_ids=included_source_ids,
                self_participant_ids=self_participant_ids,
            )
        await self._run_quick(job_id)

    def _start_quick(self, job_id: str) -> asyncio.Task[None]:
        existing = self._quick_tasks.get(job_id)
        if existing is not None and not existing.done():
            return existing
        task = asyncio.create_task(
            self._run_quick(job_id),
            name=f"history-import-quick:{job_id}",
        )
        self._quick_tasks[job_id] = task
        task.add_done_callback(partial(self._quick_task_finished, job_id))
        return task

    def _quick_task_finished(
        self,
        job_id: str,
        task: asyncio.Task[None],
    ) -> None:
        if self._quick_tasks.get(job_id) is task:
            self._quick_tasks.pop(job_id, None)
            self._confirmation_payloads.pop(job_id, None)
        if task.cancelled():
            return
        task.exception()

    async def _run_quick(self, job_id: str) -> None:
        """Idempotently finish the quick L1 boundary for one confirmed scope."""

        try:
            async with self._operation():
                async with self._lock_for(job_id):
                    job = await self._get_job_progress(job_id)
                    if job.status == "deleted":
                        return
                    if job.quick_ready:
                        self._start_background(job_id)
                        return
                    if not self._scope_confirmed(job):
                        raise HistoryImportValidationError("history_import_not_confirmed")
                    await self._store.mark_running(job_id=job_id)
                    expected_epoch = self._memory.memory_operation_epoch()
                    quick_records = await self._store.select_quick_records(job_id=job_id)
            for record in quick_records:
                async with self._operation():
                    async with self._lock_for(job_id):
                        await self._store_raw_record(
                            record,
                            quick=True,
                            expected_epoch=expected_epoch,
                        )
                await asyncio.sleep(0)
            async with self._operation():
                async with self._lock_for(job_id):
                    await self._store.mark_quick_ready(job_id=job_id)
                    quick_ready_job = await self._get_job_progress(job_id)
                    await self._log_job_checkpoint(
                        checkpoint="quick_ready",
                        job=quick_ready_job,
                    )
                    await self._log_integrity_audit(checkpoint="quick_ready")
            self._start_background(job_id)
        except asyncio.CancelledError:
            logger.info(
                "History import quick task cancelled",
                process_id=os.getpid(),
                job_id=job_id,
            )
            raise
        except _HistoryImportEpochChanged as exc:
            logger.warning(
                "History import quick task stopped because the memory clear epoch changed",
                process_id=os.getpid(),
                job_id=job_id,
            )
            async with self._operation():
                async with self._lock_for(job_id):
                    await self._store.mark_deleted(job_id=job_id)
            raise HistoryImportValidationError("memory_cleared_during_import") from exc
        except HistoryImportValidationError:
            raise
        except Exception as exc:
            logger.exception(
                "History import quick task failed",
                job_id=job_id,
                error_type=type(exc).__name__,
            )
            async with self._operation():
                async with self._lock_for(job_id):
                    await self._store.mark_failed(
                        job_id=job_id,
                        error_text=type(exc).__name__,
                    )

    def _start_background(self, job_id: str) -> None:
        existing = self._tasks.get(job_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            self._run_background(job_id),
            name=f"history-import:{job_id}",
        )
        self._tasks[job_id] = task
        task.add_done_callback(partial(self._task_finished, job_id))

    def _task_finished(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is task:
            self._tasks.pop(job_id, None)

    async def _run_background(self, job_id: str) -> None:
        try:
            async with self._operation():
                async with self._lock_for(job_id):
                    expected_epoch = self._memory.memory_operation_epoch()
                    await self._store.mark_running(job_id=job_id)
                    running_job = await self._get_job_progress(job_id)
                    await self._log_job_checkpoint(
                        checkpoint="background_started",
                        job=running_job,
                    )
            while True:
                async with self._operation():
                    async with self._lock_for(job_id):
                        records = await self._store.list_pending_raw_records(
                            job_id=job_id,
                            limit=RAW_BATCH_SIZE,
                        )
                if not records:
                    break
                for record in records:
                    async with self._operation():
                        async with self._lock_for(job_id):
                            await self._store_raw_record(
                                record,
                                quick=False,
                                expected_epoch=expected_epoch,
                            )
                async with self._operation():
                    async with self._lock_for(job_id):
                        raw_job = await self._get_job_progress(job_id)
                        await self._log_job_checkpoint(
                            checkpoint="raw_batch_completed",
                            job=raw_job,
                            batch_record_count=len(records),
                        )
                await asyncio.sleep(0)

            while True:
                async with self._operation():
                    async with self._lock_for(job_id):
                        records = await self._store.list_pending_projection_records(
                            job_id=job_id,
                            limit=PROJECTION_BATCH_SIZE,
                        )
                if not records:
                    break
                for record in records:
                    async with self._operation():
                        async with self._lock_for(job_id):
                            await self._project_record(
                                record,
                                expected_epoch=expected_epoch,
                            )
                async with self._operation():
                    async with self._lock_for(job_id):
                        projection_job = await self._get_job_progress(job_id)
                        await self._log_job_checkpoint(
                            checkpoint="projection_batch_completed",
                            job=projection_job,
                            batch_record_count=len(records),
                        )
                await asyncio.sleep(0)
            async with self._operation():
                async with self._lock_for(job_id):
                    await self._store.mark_completed(job_id=job_id)
                    completed_job = await self._get_job_progress(job_id)
                    await self._log_job_checkpoint(
                        checkpoint="completed",
                        job=completed_job,
                    )
                    await self._log_integrity_audit(checkpoint="completed")
            if self._consolidation_request is not None:
                try:
                    await self._consolidation_request()
                except Exception:
                    logger.exception("History import consolidation request failed")
        except asyncio.CancelledError:
            logger.info(
                "History import background task cancelled",
                process_id=os.getpid(),
                job_id=job_id,
            )
            raise
        except _HistoryImportEpochChanged:
            logger.warning(
                "History import stopped because the memory clear epoch changed",
                process_id=os.getpid(),
                job_id=job_id,
            )
            async with self._operation():
                async with self._lock_for(job_id):
                    await self._store.mark_deleted(job_id=job_id)
        except Exception as exc:
            logger.exception(
                "History import failed",
                job_id=job_id,
                error=repr(exc),
            )
            async with self._operation():
                async with self._lock_for(job_id):
                    await self._store.mark_failed(
                        job_id=job_id,
                        error_text=type(exc).__name__,
                    )

    async def _store_raw_record(
        self,
        record: HistoryImportRecord,
        *,
        quick: bool,
        expected_epoch: int,
    ) -> None:
        event = _memory_event_for_record(record)
        async with self._memory.governed_l1_write_guard():
            if self._memory.memory_operation_epoch() != expected_epoch:
                raise _HistoryImportEpochChanged
            stored_event_id = await self._memory.store_governed_l1_event_under_write_lock(event)
        if stored_event_id is None:
            logger.warning(
                "History import raw event was not stored",
                process_id=os.getpid(),
                job_id=record.job_id,
                job_record_id=record.job_record_id,
                event_id=event.event_id,
                quick=quick,
            )
            await self._store.mark_raw_skipped(
                job_id=record.job_id,
                job_record_id=record.job_record_id,
            )
            return
        await self._store.mark_raw_stored(
            job_id=record.job_id,
            job_record_id=record.job_record_id,
            quick=quick,
        )

    async def _project_record(
        self,
        record: HistoryImportRecord,
        *,
        expected_epoch: int,
    ) -> None:
        result = await self._memory.ingest_event(
            _memory_event_for_record(record),
            expected_epoch=expected_epoch,
        )
        if result.get("skip_reason") == "memory_clear_epoch_changed":
            raise _HistoryImportEpochChanged
        event_id = str(result.get("event_id") or record.event_id)
        handed_off = bool(result.get("l2_job_enqueued"))
        governed_skip = bool(
            result.get("skipped") or result.get("skipped_derivations") or result.get("skip_reason")
        )
        if not handed_off and not governed_skip:
            l2_store = getattr(self._memory, "l2", None)
            has_projection_job = getattr(l2_store, "has_projection_job", None)
            if callable(has_projection_job):
                try:
                    handed_off = bool(await has_projection_job(event_id=event_id))
                except Exception as exc:
                    logger.warning(
                        "History import could not verify an existing L2 projection job",
                        process_id=os.getpid(),
                        job_id=record.job_id,
                        job_record_id=record.job_record_id,
                        event_id=event_id,
                        error=type(exc).__name__,
                    )
        if governed_skip or not handed_off:
            logger.warning(
                "History import projection was skipped",
                process_id=os.getpid(),
                job_id=record.job_id,
                job_record_id=record.job_record_id,
                event_id=event_id,
                skip_reason=result.get("skip_reason"),
            )
            await self._store.mark_projection_skipped(
                job_id=record.job_id,
                job_record_id=record.job_record_id,
            )
            return
        await self._store.mark_projected(
            job_id=record.job_id,
            job_record_id=record.job_record_id,
        )

    async def _log_job_checkpoint(
        self,
        *,
        checkpoint: str,
        job: HistoryImportJob,
        batch_record_count: int | None = None,
    ) -> None:
        """Log progress counters without recording imported names or content."""

        l1_event_count = await self._l1_history_event_count()
        logger.info(
            "History import checkpoint",
            process_id=os.getpid(),
            checkpoint=checkpoint,
            job_id=job.job_id,
            status=job.status,
            total_record_count=job.total_records,
            quick_imported_count=job.quick_imported_count,
            imported_count=job.imported_count,
            projected_count=job.projected_count,
            quick_ready=job.quick_ready,
            batch_record_count=batch_record_count,
            l1_history_event_count=l1_event_count,
        )

    async def _log_integrity_audit(self, *, checkpoint: str) -> None:
        """Compare the import ledger with active L1 rows without logging content."""

        try:
            jobs = await self._store.list_active_jobs(limit=100)
            ledger_imported_count = await self._store.count_active_imported_events()
            l1_event_count = await self._l1_history_event_count()
            audit_truncated = len(jobs) == 100
            consistent = None if l1_event_count is None else ledger_imported_count == l1_event_count
            log = logger.warning if consistent is False else logger.info
            log(
                "History import integrity audit",
                process_id=os.getpid(),
                checkpoint=checkpoint,
                active_job_count=len(jobs),
                completed_job_count=sum(1 for job in jobs if job.status == "completed"),
                ledger_imported_count=ledger_imported_count,
                l1_history_event_count=l1_event_count,
                consistent=consistent,
                audit_truncated=audit_truncated,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "History import integrity audit unavailable",
                process_id=os.getpid(),
                checkpoint=checkpoint,
                error_type=type(exc).__name__,
            )

    async def _l1_history_event_count(self) -> int | None:
        l1 = getattr(self._memory, "l1", None)
        counter = getattr(l1, "count_events", None)
        if not callable(counter):
            return None
        try:
            return int(await counter(source_filters=[HISTORY_IMPORT_SOURCE]))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "History import L1 count unavailable",
                process_id=os.getpid(),
                error_type=type(exc).__name__,
            )
            return None

    def _lock_for(self, job_id: str) -> asyncio.Lock:
        return self._locks.setdefault(job_id, asyncio.Lock())

    @staticmethod
    def _scope_confirmed(job: HistoryImportJob) -> bool:
        return bool(job.included_source_ids and job.self_participant_ids)

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        """Keep clear-lock ordering stable across API and background entry points."""

        async with self._memory.memory_operation_guard():
            async with self._operation_barrier.operation():
                yield

    async def _cancel_background_tasks(self) -> None:
        tasks = [*self._quick_tasks.values(), *self._tasks.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._quick_tasks.clear()
        self._tasks.clear()
        self._confirmation_payloads.clear()

    async def _drain_importer_parse_tasks(self) -> None:
        """Give active parser workers a bounded chance to finish during shutdown."""

        tasks = set(self._importer_parse_tasks)
        if not tasks:
            return
        _done, pending = await asyncio.wait(
            tasks,
            timeout=IMPORTER_PARSE_SHUTDOWN_GRACE_SECONDS,
        )
        if pending:
            logger.warning(
                "History importer workers remain active after shutdown grace period",
                process_id=os.getpid(),
                pending_worker_count=len(pending),
            )


def _platform_import_fingerprint(
    registered: RegisteredHistoryImporter,
    resolved_paths: list[Path],
) -> str:
    """Hash selected archives outside the async service loop."""

    fingerprint_hash = hashlib.sha256()
    for part in (
        registered.connection_id,
        registered.plugin_id,
        registered.importer_id,
        registered.spec.format_version,
    ):
        fingerprint_hash.update(part.encode("utf-8"))
        fingerprint_hash.update(b"\x00")
    file_digests: list[bytes] = []
    for path in resolved_paths:
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                file_hash.update(chunk)
        file_digests.append(file_hash.digest())
    for file_digest in sorted(file_digests):
        fingerprint_hash.update(file_digest)
        fingerprint_hash.update(b"\x00")
    return fingerprint_hash.hexdigest()


def _run_history_importer_in_worker(
    registered: RegisteredHistoryImporter,
    resolved_paths: list[Path],
) -> Any:
    """Run synchronous or asynchronous parser code inside one worker thread."""

    result = registered.importer.parse(resolved_paths)
    if inspect.isawaitable(result):
        result = asyncio.run(_await_history_importer_result(result))
    return _revalidate_importer_output(result)


async def _await_history_importer_result(result: Any) -> Any:
    """Await a parser result inside the worker thread's private event loop."""

    return await result


def _parse_markdown_selection(
    paths: list[str],
) -> tuple[list[ParsedHistorySource], dict[str, str], str, list[str]]:
    """Read one bounded Markdown selection into deterministic preview inputs."""

    files = _expand_markdown_paths(paths)
    parsed_files: list[ParsedHistorySource] = []
    file_fingerprints: dict[str, str] = {}
    fingerprint_parts: list[bytes] = []
    total_bytes = 0
    calendar_timezone_id = local_calendar_timezone_id()
    if calendar_timezone_id is None:
        raise HistoryImportValidationError("history_import_timezone_unavailable")
    for path, source_name in files:
        size = int(path.stat().st_size)
        if size > MAX_MARKDOWN_FILE_BYTES:
            raise HistoryImportValidationError("markdown_file_too_large")
        total_bytes += size
        if total_bytes > MAX_MARKDOWN_TOTAL_BYTES:
            raise HistoryImportValidationError("markdown_selection_too_large")
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HistoryImportValidationError("markdown_not_utf8") from exc
        normalized_source_name = _normalized_relative_source_name(source_name)
        file_fingerprint = hashlib.sha256(
            normalized_source_name.encode("utf-8") + b"\x00" + raw
        ).hexdigest()
        file_fingerprints[source_name] = file_fingerprint
        parsed_files.append(
            parse_markdown(
                source_name=source_name,
                text=text,
                file_mtime=float(path.stat().st_mtime),
                calendar_timezone_id=calendar_timezone_id,
            )
        )
        fingerprint_parts.append(bytes.fromhex(file_fingerprint))
    fingerprint = hashlib.sha256(
        b"\x00".join([MARKDOWN_IMPORT_POLICY_VERSION, *fingerprint_parts])
    ).hexdigest()
    warnings = list(
        dict.fromkeys(warning for parsed in parsed_files for warning in parsed.warnings)
    )
    return parsed_files, file_fingerprints, fingerprint, warnings


def _expand_markdown_paths(paths: list[str]) -> list[tuple[Path, str]]:
    normalized = list(
        dict.fromkeys(str(value or "").strip() for value in paths if str(value or "").strip())
    )
    if not normalized:
        raise HistoryImportValidationError("markdown_selection_empty")
    selected: list[tuple[Path, str]] = []
    for raw_path in normalized:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise HistoryImportValidationError("markdown_path_missing")
        if path.is_file():
            if path.suffix.casefold() not in {".md", ".markdown"}:
                raise HistoryImportValidationError("markdown_extension_required")
            selected.append((path.resolve(), path.name))
            continue
        if not path.is_dir():
            raise HistoryImportValidationError("markdown_path_invalid")
        for child in sorted(path.rglob("*")):
            if (
                child.is_file()
                and child.suffix.casefold() in {".md", ".markdown"}
                and not any(part.startswith(".") for part in child.relative_to(path).parts)
            ):
                selected.append((child.resolve(), str(child.relative_to(path))))
    deduped: dict[str, tuple[Path, str]] = {}
    for path, source_name in selected:
        deduped[str(path)] = (path, source_name)
    files = _unique_source_names(sorted(deduped.values(), key=lambda item: item[1].casefold()))
    if not files:
        raise HistoryImportValidationError("markdown_files_not_found")
    if len(files) > MAX_MARKDOWN_FILES:
        raise HistoryImportValidationError("markdown_too_many_files")
    return files


def _validate_importer_paths(
    paths: list[str],
    registered: RegisteredHistoryImporter,
) -> list[Path]:
    normalized = list(
        dict.fromkeys(str(value or "").strip() for value in paths if str(value or "").strip())
    )
    if not normalized:
        raise HistoryImportValidationError("history_import_selection_empty")
    if len(normalized) > 10:
        raise HistoryImportValidationError("history_importer_too_many_files")
    accepted = {f".{value}" for value in registered.spec.accepted_extensions}
    resolved: list[Path] = []
    total_bytes = 0
    for raw_path in normalized:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise HistoryImportValidationError("history_importer_file_required")
        if path.suffix.casefold() not in accepted:
            raise HistoryImportValidationError("history_importer_extension_not_supported")
        total_bytes += int(path.stat().st_size)
        if total_bytes > 250 * 1024 * 1024:
            raise HistoryImportValidationError("history_importer_selection_too_large")
        resolved.append(path.resolve())
    return resolved


def _platform_participant_id(
    *,
    registered: RegisteredHistoryImporter,
    source_id: str,
    raw_speaker_id: str,
) -> str:
    """Return an opaque host identity with the importer's declared scope."""

    if raw_speaker_id == DOCUMENT_AUTHOR:
        raise HistoryImportValidationError("history_importer_reserved_participant_id")
    identity_parts = [
        registered.connection_id,
        registered.plugin_id,
        registered.importer_id,
        registered.spec.format_version,
    ]
    if registered.spec.participant_identity_scope == "source":
        identity_parts.append(source_id)
    identity_parts.append(raw_speaker_id)
    digest = hashlib.sha256("\x00".join(identity_parts).encode("utf-8")).hexdigest()
    return f"hip_{digest[:32]}"


def _revalidate_importer_output(value: Any) -> HistoryImportParseResult:
    """Rebuild plugin output from plain data before trusting SDK invariants."""

    try:
        plain_value = _bounded_history_import_payload(value)
    except _HistoryImporterOutputInvalid:
        raise
    except Exception as exc:
        raise _HistoryImporterOutputInvalid from exc
    return HistoryImportParseResult.model_validate(plain_value)


_MISSING_IMPORT_FIELD = object()
_PARSE_RESULT_FIELDS = ("sources", "warnings")
_SOURCE_FIELDS = (
    "source_id",
    "source_name",
    "session_key",
    "detected_kind",
    "records",
    "warnings",
)
_RECORD_FIELDS = (
    "message_key",
    "source_order",
    "speaker_id",
    "speaker_name",
    "role_hint",
    "content",
    "occurred_at",
    "timestamp_confidence",
    "parent_message_key",
)


def _bounded_history_import_payload(value: Any) -> dict[str, Any]:
    """Copy only the declared importer schema while enforcing budgets first."""

    payload = _known_import_fields(value, _PARSE_RESULT_FIELDS)
    sources = _import_sequence(_required_import_field(payload, "sources"))
    if len(sources) > MAX_HISTORY_IMPORT_SOURCES:
        raise _HistoryImporterOutputTooLarge
    payload["warnings"] = _bounded_importer_warnings(
        payload.get("warnings", []),
        maximum=MAX_HISTORY_IMPORT_WARNINGS,
    )

    total_records = 0
    total_content_chars = 0
    copied_sources: list[dict[str, Any]] = []
    for source_value in sources:
        source = _known_import_fields(source_value, _SOURCE_FIELDS)
        records = _import_sequence(_required_import_field(source, "records"))
        if len(records) > MAX_HISTORY_IMPORT_RECORDS_PER_SOURCE:
            raise _HistoryImporterOutputTooLarge
        total_records += len(records)
        if total_records > MAX_IMPORTER_TOTAL_RECORDS:
            raise _HistoryImporterOutputTooLarge
        source["warnings"] = _bounded_importer_warnings(
            source.get("warnings", []),
            maximum=MAX_HISTORY_IMPORT_SOURCE_WARNINGS,
        )

        copied_records: list[dict[str, Any]] = []
        for record_value in records:
            record = _known_import_fields(record_value, _RECORD_FIELDS)
            content = _required_import_field(record, "content")
            if not isinstance(content, str):
                raise _HistoryImporterOutputInvalid
            content_length = len(content)
            if content_length > MAX_HISTORY_IMPORT_CONTENT_LENGTH:
                raise _HistoryImporterOutputTooLarge
            total_content_chars += content_length
            if total_content_chars > MAX_IMPORTER_TOTAL_CONTENT_CHARS:
                raise _HistoryImporterOutputTooLarge
            copied_records.append(record)
        source["records"] = copied_records
        copied_sources.append(source)
    payload["sources"] = copied_sources
    return payload


def _known_import_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        source = value.__dict__
    elif type(value) is dict:  # noqa: E721 - exclude plugin-defined mappings
        source = value
    else:
        raise _HistoryImporterOutputInvalid
    return {field: source[field] for field in fields if field in source}


def _required_import_field(payload: dict[str, Any], field: str) -> Any:
    value = payload.get(field, _MISSING_IMPORT_FIELD)
    if value is _MISSING_IMPORT_FIELD:
        raise _HistoryImporterOutputInvalid
    return value


def _import_sequence(value: Any) -> list[Any] | tuple[Any, ...]:
    # Exact built-ins exclude plugin-defined containers with untrusted length behavior.
    if type(value) not in {list, tuple}:  # noqa: E721
        raise _HistoryImporterOutputInvalid
    return value


def _bounded_importer_warnings(value: Any, *, maximum: int) -> list[Any]:
    warnings = _import_sequence(value)
    if len(warnings) > maximum:
        raise _HistoryImporterOutputTooLarge
    copied: list[Any] = []
    for warning in warnings:
        if isinstance(warning, str) and len(warning) > MAX_HISTORY_IMPORT_WARNING_LENGTH:
            raise _HistoryImporterOutputTooLarge
        copied.append(warning)
    return copied


def _validation_error_is_size_limit(exc: ValidationError) -> bool:
    return any(
        str(error.get("type") or "") in {"too_long", "string_too_long"}
        for error in exc.errors(include_url=False)
    )


def _bounded_import_warnings(warnings: list[str]) -> list[str]:
    unique = list(dict.fromkeys(warnings))
    if len(unique) <= MAX_STORED_IMPORT_WARNINGS:
        return unique
    return [
        *unique[: MAX_STORED_IMPORT_WARNINGS - 1],
        f"history_import_warnings_truncated:{len(unique)}",
    ]


def _is_meaningful_imported_message(content: str) -> bool:
    normalized = re.sub(r"\s+", " ", content).strip()
    return len(normalized) >= 2 and bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", normalized))


def _unique_source_names(
    files: list[tuple[Path, str]],
) -> list[tuple[Path, str]]:
    """Keep selection labels distinct without exposing full local paths."""

    label_counts = Counter(source_name.casefold() for _, source_name in files)
    used: set[str] = set()
    resolved: list[tuple[Path, str]] = []
    for path, source_name in files:
        candidate = source_name
        if label_counts[source_name.casefold()] > 1:
            safe_parts = [part for part in path.parts if part and part != path.anchor]
            for depth in range(2, min(len(safe_parts), 3) + 1):
                candidate = "/".join(safe_parts[-depth:])
                if candidate.casefold() not in used:
                    break
            else:
                candidate = source_name
        base_candidate = candidate
        suffix = 2
        while candidate.casefold() in used:
            candidate = f"{base_candidate} ({suffix})"
            suffix += 1
        used.add(candidate.casefold())
        resolved.append((path, candidate))
    return resolved


def _validate_included_sources(
    job: HistoryImportJob,
    included_source_ids: list[str],
    *,
    allow_empty: bool = False,
) -> list[str]:
    normalized = list(
        dict.fromkeys(
            str(item or "").strip() for item in included_source_ids if str(item or "").strip()
        )
    )
    if not normalized and not allow_empty:
        raise HistoryImportValidationError("history_import_selection_empty")
    known = set(job.source_ids)
    if any(item not in known for item in normalized):
        raise HistoryImportValidationError("history_import_selection_changed")
    return [item for item in job.source_ids if item in set(normalized)]


def _confirmation_payload(
    *,
    confirm_personal_writing: bool,
    included_source_ids: list[str] | None,
    self_participant_ids: list[str] | None,
) -> tuple[bool, tuple[str, ...] | None, tuple[str, ...]]:
    """Return the canonical identity of one in-flight confirmation request."""

    normalized_sources = (
        None
        if included_source_ids is None
        else tuple(
            sorted(
                {str(item or "").strip() for item in included_source_ids if str(item or "").strip()}
            )
        )
    )
    normalized_participants = tuple(
        sorted(
            {
                str(item or "").strip()
                for item in (self_participant_ids or [])
                if str(item or "").strip()
            }
        )
    )
    return (
        bool(confirm_personal_writing),
        normalized_sources,
        normalized_participants,
    )


def _build_records(
    *,
    job_id: str,
    file_fingerprints: dict[str, str],
    parsed_files: list[ParsedHistorySource],
    now: float,
    importer_identity: tuple[str, str, str, str] | None = None,
    missing_timestamp_anchor: float | None = None,
) -> list[HistoryImportRecord]:
    records: list[HistoryImportRecord] = []
    for parsed in parsed_files:
        if importer_identity is None:
            file_fingerprint = file_fingerprints[parsed.source_name]
            session_identity = f"{file_fingerprint}\x00{parsed.session_key}"
        else:
            connection_id, plugin_id, importer_id, format_version = importer_identity
            session_identity = "\x00".join(
                (
                    connection_id,
                    plugin_id,
                    importer_id,
                    format_version,
                    parsed.source_id,
                    parsed.session_key,
                )
            )
            file_fingerprint = hashlib.sha256(session_identity.encode("utf-8")).hexdigest()
        session_digest = hashlib.sha256(session_identity.encode("utf-8")).hexdigest()[:24]
        session_id = f"history_{session_digest}"
        ordered_records = sorted(parsed.records, key=lambda item: int(item.get("source_order", 0)))
        known_times = [
            (index, float(item["event_at"]))
            for index, item in enumerate(ordered_records)
            if item.get("event_at") is not None
        ]
        for session_seq, item in enumerate(ordered_records):
            if importer_identity is None:
                identity = "\x00".join(
                    (
                        file_fingerprint,
                        parsed.session_key,
                        str(session_seq),
                        str(item["speaker_name"]),
                        str(item["content"]),
                    )
                )
            else:
                identity = "\x00".join(
                    (
                        *importer_identity,
                        parsed.source_id,
                        parsed.session_key,
                        str(item["message_key"]),
                    )
                )
            source_digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            source_record_key = f"hisr_{source_digest[:32]}"
            event_digest = hashlib.sha256(
                f"history-event\x00{source_record_key}".encode("utf-8")
            ).hexdigest()
            job_record_digest = hashlib.sha256(
                f"{job_id}\x00{source_record_key}".encode("utf-8")
            ).hexdigest()
            event_at = item.get("event_at")
            if event_at is None:
                event_at = _ordered_timestamp_anchor(
                    session_seq=session_seq,
                    known_times=known_times,
                    fallback=(
                        missing_timestamp_anchor if missing_timestamp_anchor is not None else now
                    ),
                )
            records.append(
                HistoryImportRecord(
                    job_record_id=f"hijr_{job_record_digest[:32]}",
                    job_id=job_id,
                    source_record_key=source_record_key,
                    file_fingerprint=file_fingerprint,
                    source_id=parsed.source_id,
                    source_name=parsed.source_name,
                    source_kind=parsed.detected_kind,
                    parsed_session_key=parsed.session_key,
                    session_id=session_id,
                    session_seq=session_seq,
                    speaker_id=str(item.get("speaker_id") or item["speaker_name"]),
                    speaker_name=str(item["speaker_name"]),
                    message_key=str(item.get("message_key") or session_seq),
                    parent_message_key=(
                        str(item["parent_message_key"])
                        if item.get("parent_message_key") is not None
                        else None
                    ),
                    content=str(item["content"]),
                    event_at=float(event_at),
                    timestamp_confidence=str(item["timestamp_confidence"]),
                    timestamp_anchor_source=str(item["timestamp_anchor_source"]),
                    calendar_timezone_id=str(item["calendar_timezone_id"]),
                    meaningful=bool(item["meaningful"]),
                    event_id=f"hi_{event_digest[:32]}",
                    created_at=now,
                    updated_at=now,
                )
            )
    records.sort(key=lambda item: (item.session_id, item.session_seq))
    return records


def _ordered_timestamp_anchor(
    *,
    session_seq: int,
    known_times: list[tuple[int, float]],
    fallback: float,
) -> float:
    """Place an undated record near declared neighbors without claiming exact time."""

    previous = [item for item in known_times if item[0] < session_seq]
    if previous:
        previous_seq, previous_time = previous[-1]
        return previous_time + ((session_seq - previous_seq) / 1_000_000)
    following = [item for item in known_times if item[0] > session_seq]
    if following:
        following_seq, following_time = following[0]
        return following_time - ((following_seq - session_seq) / 1_000_000)
    return fallback + (session_seq / 1_000_000)


def _memory_event_for_record(record: HistoryImportRecord) -> MemoryEvent:
    is_user = record.speaker_role == "user"
    source_kind = record.source_kind
    now = time.time()
    return MemoryEvent(
        event_id=record.event_id,
        correlation_id=f"history-import:{record.source_record_key}",
        timestamp=float(record.event_at),
        created_at=now,
        event_type=f"history_import.{source_kind}",
        source=HISTORY_IMPORT_SOURCE,
        source_item_id=record.source_record_key,
        memory_domain=(MemoryDomain.USER_AUTHORED if is_user else MemoryDomain.INTERACTION),
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=is_user,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=record.session_id,
        turn_id=None,
        session_seq=record.session_seq,
        user_id=str(CANONICAL_LOCAL_USER),
        task_id=None,
        content=record.content,
        author_type=(AuthorType.USER.label if is_user else AuthorType.EXTERNAL.label),
        content_type=ContentType.TEXT.label,
        importance_score=0.72 if is_user else 0.3,
        level=0,
        idempotency_key=f"history-import:{record.source_record_key}",
        metadata_json=with_calendar_timezone(
            {
                "history_import": {
                    "source_record_key": record.source_record_key,
                    "file_fingerprint": record.file_fingerprint,
                    "source_id": record.source_id,
                    "source_name": record.source_name,
                    "source_kind": record.source_kind,
                    "speaker_id": record.speaker_id,
                    "speaker_name": record.speaker_name,
                    "message_key": record.message_key,
                    "parent_message_key": record.parent_message_key,
                    "speaker_role": record.speaker_role,
                    "timestamp_confidence": record.timestamp_confidence,
                    "timestamp_anchor_source": record.timestamp_anchor_source,
                    "historical": True,
                },
                "l2_batch_owner": f"history-import:{record.session_id}",
                "l2_batch_max_events": 40,
                "l2_batch_min_ready_events": 20,
                "l2_batch_max_wait_seconds": 1,
            },
            calendar_timezone_id=record.calendar_timezone_id,
        ),
    )


def _normalized_relative_source_name(source_name: str) -> str:
    return unicodedata.normalize("NFKC", str(source_name)).replace("\\", "/").strip()


__all__ = [
    "HistoryImportError",
    "HistoryImportNotFoundError",
    "HistoryImportService",
    "HistoryImportValidationError",
    "MAX_MARKDOWN_FILES",
    "MAX_MARKDOWN_FILE_BYTES",
    "MAX_MARKDOWN_TOTAL_BYTES",
    "SOURCE_PREVIEW_MAX_CHARS",
    "SOURCE_PREVIEW_MAX_RECORDS",
]
