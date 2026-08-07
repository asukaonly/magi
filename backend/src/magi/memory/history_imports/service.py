"""Host-owned Markdown preview, quick context, and ordered background import."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
from functools import partial
import hashlib
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

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
    HistoryImportJob,
    HistoryImportRecord,
    HistoryImportSourcePreview,
    ParsedHistoryFile,
)
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
HISTORY_IMPORT_SOURCE = "history_import_markdown"


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


class HistoryImportService:
    """Create previews and advance imports without letting adapters write memory."""

    def __init__(self, *, store: HistoryImportStore, memory: Any) -> None:
        self._store = store
        self._memory = memory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._deletion_lock = asyncio.Lock()
        self._operation_barrier = AsyncOperationBarrier()

    async def start(self) -> None:
        """Resume imports that had already reached the quick-ready boundary."""

        async with self._operation():
            await self._log_integrity_audit(checkpoint="startup")
            resumable_job_ids = await self._store.list_resumable_job_ids()
            logger.info(
                "History import service started",
                process_id=os.getpid(),
                resumable_job_count=len(resumable_job_ids),
            )
            for job_id in resumable_job_ids:
                self._start_background(job_id)

    async def stop(self) -> None:
        async with self._operation_barrier.exclusive():
            await self._cancel_background_tasks()
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

        files = _expand_markdown_paths(paths)
        parsed_files: list[ParsedHistoryFile] = []
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

        fingerprint = hashlib.sha256(b"\x00".join(fingerprint_parts)).hexdigest()
        existing = await self._store.find_active_by_fingerprint(fingerprint)
        if existing is not None:
            return existing

        now = time.time()
        job_id = f"him_{uuid.uuid4().hex}"
        detected_kinds = {item.detected_kind for item in parsed_files}
        detected_kind = next(iter(detected_kinds)) if len(detected_kinds) == 1 else "mixed"
        warnings = list(
            dict.fromkeys(warning for parsed in parsed_files for warning in parsed.warnings)
        )
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
            source_files=[source_name for _, source_name in files],
            included_files=[source_name for _, source_name in files],
            detected_kind=detected_kind,
            status="preview_ready",
            total_records=len(records),
            meaningful_records=sum(1 for record in records if record.meaningful),
            quick_target_records=QUICK_TARGET_RECORDS,
            quick_max_records=QUICK_MAX_RECORDS,
            quick_imported_count=0,
            imported_count=0,
            projected_count=0,
            self_participants=[],
            warnings=warnings,
            quick_ready=False,
            created_at=now,
            updated_at=now,
        )
        return await self._store.create_preview(job=job, records=records)

    async def get_job(self, job_id: str) -> HistoryImportJob:
        async with self._operation():
            return await self._get_job(job_id)

    async def _get_job(self, job_id: str) -> HistoryImportJob:
        job = await self._store.get_job(job_id)
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
        source_name: str,
    ) -> HistoryImportSourcePreview:
        """Return a bounded preview for one file without changing its selection."""

        async with self._operation():
            return await self._get_source_preview(
                job_id=job_id,
                source_name=source_name,
            )

    async def _get_source_preview(
        self,
        *,
        job_id: str,
        source_name: str,
    ) -> HistoryImportSourcePreview:
        """Load one source preview while the service operation boundary is held."""

        job = await self._get_job(job_id)
        if source_name not in job.source_files:
            raise HistoryImportValidationError("history_import_source_not_found")
        source = next(
            item for item in job.sources if item.source_name == source_name
        )
        loaded = await self._store.list_source_records(
            job_id=job_id,
            source_name=source_name,
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
            source_name=source_name,
            detected_kind=source.detected_kind,
            records=records,
            truncated=truncated,
        )

    async def update_selection(
        self,
        *,
        job_id: str,
        included_files: list[str],
    ) -> HistoryImportJob:
        """Persist the file subset selected in the preview."""

        async with self._operation():
            return await self._update_selection(
                job_id=job_id,
                included_files=included_files,
            )

    async def _update_selection(
        self,
        *,
        job_id: str,
        included_files: list[str],
    ) -> HistoryImportJob:
        """Update selection while the service operation boundary is held."""

        lock = self._lock_for(job_id)
        async with lock:
            job = await self._get_job(job_id)
            if job.quick_ready or job.imported_count > 0:
                raise HistoryImportValidationError("history_import_selection_locked")
            normalized = _validate_included_files(
                job,
                included_files,
                allow_empty=True,
            )
            return await self._store.update_selection(
                job_id=job_id,
                included_files=normalized,
            )

    async def confirm(
        self,
        *,
        job_id: str,
        self_participants: list[str],
        confirm_personal_writing: bool,
        included_files: list[str] | None = None,
    ) -> HistoryImportJob:
        """Confirm identity, prepare recent raw context, and continue in order."""

        async with self._operation():
            return await self._confirm(
                job_id=job_id,
                self_participants=self_participants,
                confirm_personal_writing=confirm_personal_writing,
                included_files=included_files,
            )

    async def _confirm(
        self,
        *,
        job_id: str,
        self_participants: list[str],
        confirm_personal_writing: bool,
        included_files: list[str] | None = None,
    ) -> HistoryImportJob:
        """Confirm one import while the service operation boundary is held."""

        lock = self._lock_for(job_id)
        async with lock:
            job = await self._get_job(job_id)
            if job.deleted_at is not None or job.status == "deleted":
                raise HistoryImportNotFoundError()
            selected_files = _validate_included_files(
                job,
                included_files if included_files is not None else job.included_files,
            )
            if job.quick_ready and set(job.included_files) != set(selected_files):
                raise HistoryImportValidationError("history_import_selection_locked")
            if not job.quick_ready:
                job = await self._store.update_selection(
                    job_id=job_id,
                    included_files=selected_files,
                )
            selected = list(
                dict.fromkeys(str(item).strip() for item in self_participants if str(item).strip())
            )
            participant_names = {item.name for item in job.participants}
            if any(item not in participant_names for item in selected):
                raise HistoryImportValidationError("unknown_self_participant")
            selected_kinds = {source.detected_kind for source in job.sources if source.included}
            includes_chat = bool(selected_kinds & {"chat", "mixed"})
            includes_documents = bool(selected_kinds & {"document", "mixed"})
            if includes_chat and not selected:
                raise HistoryImportValidationError("self_participant_required")
            if includes_documents:
                if not confirm_personal_writing:
                    raise HistoryImportValidationError("personal_writing_confirmation_required")
                if DOCUMENT_AUTHOR in participant_names:
                    selected.append(DOCUMENT_AUTHOR)
            selected = list(dict.fromkeys(selected))
            if not selected:
                raise HistoryImportValidationError("self_participant_required")
            if (
                job.imported_count > 0
                and job.self_participants
                and set(job.self_participants) != set(selected)
            ):
                raise HistoryImportValidationError("self_participant_locked_after_import")
            logger.info(
                "History import confirmation started",
                process_id=os.getpid(),
                job_id=job_id,
                selected_file_count=len(selected_files),
                total_record_count=job.total_records,
                imported_count=job.imported_count,
                quick_ready=job.quick_ready,
            )
            if not job.quick_ready:
                try:
                    await self._store.set_scope(
                        job_id=job_id,
                        self_participants=selected,
                        included_files=selected_files,
                    )
                except ValueError as exc:
                    if str(exc) != "history_import_speaker_role_conflict":
                        raise
                    raise HistoryImportValidationError(str(exc)) from exc
                quick_records = await self._store.select_quick_records(job_id=job_id)
                expected_epoch = self._memory.memory_operation_epoch()
                try:
                    for record in quick_records:
                        await self._store_raw_record(
                            record,
                            quick=True,
                            expected_epoch=expected_epoch,
                        )
                except _HistoryImportEpochChanged as exc:
                    await self._store.mark_deleted(job_id=job_id)
                    raise HistoryImportValidationError("memory_cleared_during_import") from exc
                await self._store.mark_quick_ready(job_id=job_id)
                quick_ready_job = await self._get_job(job_id)
                await self._log_job_checkpoint(
                    checkpoint="quick_ready",
                    job=quick_ready_job,
                )
                await self._log_integrity_audit(checkpoint="quick_ready")
            self._start_background(job_id)
        return await self._get_job(job_id)

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
            if record.source_name in seen_sources:
                continue
            selected.append(record)
            seen_sources.add(record.source_name)
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
        job = await self._get_job(job_id)
        if not job.quick_ready:
            raise HistoryImportValidationError("history_import_not_confirmed")
        if job.status not in {"completed", "deleted"}:
            await self._store.mark_running(job_id=job_id)
            self._start_background(job_id)
        return await self._get_job(job_id)

    async def delete(self, job_id: str) -> None:
        async with self._operation():
            await self._delete(job_id)

    async def _delete(self, job_id: str) -> None:
        task = self._tasks.pop(job_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._deletion_lock:
            async with self._lock_for(job_id):
                job = await self._get_job(job_id)
                if job.status == "deleted":
                    return
                event_ids = await self._store.list_unreferenced_event_ids_for_delete(
                    job_id=job_id
                )
                logger.info(
                    "History import deletion started",
                    process_id=os.getpid(),
                    job_id=job_id,
                    unreferenced_event_count=len(event_ids),
                )
                if event_ids:
                    await self._memory.forget_known_source_events(
                        event_ids,
                        reason="history_import_deleted",
                        block_source_item=False,
                    )
                await self._store.mark_deleted(job_id=job_id)
                await self._log_integrity_audit(checkpoint="deleted")

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
                    running_job = await self._get_job(job_id)
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
                        raw_job = await self._get_job(job_id)
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
                        projection_job = await self._get_job(job_id)
                        await self._log_job_checkpoint(
                            checkpoint="projection_batch_completed",
                            job=projection_job,
                            batch_record_count=len(records),
                        )
                await asyncio.sleep(0)
            async with self._operation():
                async with self._lock_for(job_id):
                    await self._store.mark_completed(job_id=job_id)
                    completed_job = await self._get_job(job_id)
                    await self._log_job_checkpoint(
                        checkpoint="completed",
                        job=completed_job,
                    )
                    await self._log_integrity_audit(checkpoint="completed")
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
        if result.get("skipped") or not result.get("l2_job_enqueued"):
            logger.warning(
                "History import projection was skipped",
                process_id=os.getpid(),
                job_id=record.job_id,
                job_record_id=record.job_record_id,
                event_id=record.event_id,
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
            consistent = (
                None
                if l1_event_count is None
                else ledger_imported_count == l1_event_count
            )
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

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        """Keep clear-lock ordering stable across API and background entry points."""

        async with self._memory.memory_operation_guard():
            async with self._operation_barrier.operation():
                yield

    async def _cancel_background_tasks(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


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


def _validate_included_files(
    job: HistoryImportJob,
    included_files: list[str],
    *,
    allow_empty: bool = False,
) -> list[str]:
    normalized = list(
        dict.fromkeys(str(item or "").strip() for item in included_files if str(item or "").strip())
    )
    if not normalized and not allow_empty:
        raise HistoryImportValidationError("history_import_selection_empty")
    known = set(job.source_files)
    if any(item not in known for item in normalized):
        raise HistoryImportValidationError("history_import_selection_changed")
    return [item for item in job.source_files if item in set(normalized)]


def _build_records(
    *,
    job_id: str,
    file_fingerprints: dict[str, str],
    parsed_files: list[ParsedHistoryFile],
    now: float,
) -> list[HistoryImportRecord]:
    records: list[HistoryImportRecord] = []
    for parsed in parsed_files:
        file_fingerprint = file_fingerprints[parsed.source_name]
        session_digest = hashlib.sha256(
            f"{file_fingerprint}\x00{parsed.session_key}".encode("utf-8")
        ).hexdigest()[:24]
        session_id = f"history_{session_digest}"
        for session_seq, item in enumerate(parsed.records):
            identity = "\x00".join(
                (
                    file_fingerprint,
                    parsed.session_key,
                    str(session_seq),
                    str(item["speaker_name"]),
                    str(item["content"]),
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
            records.append(
                HistoryImportRecord(
                    job_record_id=f"hijr_{job_record_digest[:32]}",
                    job_id=job_id,
                    source_record_key=source_record_key,
                    file_fingerprint=file_fingerprint,
                    source_name=parsed.source_name,
                    parsed_session_key=parsed.session_key,
                    session_id=session_id,
                    session_seq=session_seq,
                    speaker_name=str(item["speaker_name"]),
                    content=str(item["content"]),
                    event_at=float(item["event_at"]),
                    timestamp_confidence=str(item["timestamp_confidence"]),
                    timestamp_anchor_source=str(item["timestamp_anchor_source"]),
                    calendar_timezone_id=str(item["calendar_timezone_id"]),
                    meaningful=bool(item["meaningful"]),
                    event_id=f"hi_{event_digest[:32]}",
                    created_at=now,
                    updated_at=now,
                )
            )
    records.sort(key=lambda item: (item.event_at, item.session_id, item.session_seq))
    return records


def _memory_event_for_record(record: HistoryImportRecord) -> MemoryEvent:
    is_user = record.speaker_role == "user"
    source_kind = "document" if record.speaker_name == DOCUMENT_AUTHOR else "chat"
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
        metadata_json=with_calendar_timezone({
            "history_import": {
                "source_record_key": record.source_record_key,
                "file_fingerprint": record.file_fingerprint,
                "source_name": record.source_name,
                "speaker_name": record.speaker_name,
                "speaker_role": record.speaker_role,
                "timestamp_confidence": record.timestamp_confidence,
                "timestamp_anchor_source": record.timestamp_anchor_source,
                "historical": True,
            },
            "l2_batch_owner": f"history-import:{record.session_id}",
            "l2_batch_max_events": 40,
            "l2_batch_min_ready_events": 20,
            "l2_batch_max_wait_seconds": 1,
        }, calendar_timezone_id=record.calendar_timezone_id),
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
