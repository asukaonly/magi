"""Process-local ASR admission, cancellation, reconciliation and retention."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from magi_plugin_sdk.audio import MAX_AUDIO_BYTES, inspect_wav

from ...config import get_config
from ...config.models import AppConfig
from ...utils.runtime import RuntimePaths
from .contracts import ASRError, ASRJob, ASRStatus
from .engines import ASROptions, LocalASREngine, remote_transcribe, resolve_options
from .models import ASRModelStore

REQUEST_TTL = 120
RESULT_TTL = 120
MAX_ACTIVE = 4
MAX_RECEIPTS = 64
_ID = re.compile(r"^(\d{13})-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass
class _Entry:
    job: ASRJob
    fingerprint: str | None
    options: ASROptions | None = None
    audio: bytes = field(default=b"", repr=False)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class ASRService:
    def __init__(self, models: ASRModelStore, config: Callable[[], AppConfig] = get_config) -> None:
        self.models, self.config = models, config
        self.runtime_id = uuid.uuid4().hex
        self.entries: dict[tuple[str, str], _Entry] = {}
        self.local = LocalASREngine()
        self.compute = asyncio.Semaphore(1)
        self.admission = asyncio.Lock()
        self.last_local_use = 0.0
        self.maintenance: asyncio.Task[None] | None = None
        self.closed = False

    def _maintain(self) -> None:
        if self.maintenance is None:
            self.maintenance = asyncio.create_task(self._sweep())

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(15)
            self._prune()
            if not self.local_in_use() and time.monotonic() - self.last_local_use > 120:
                self.local.unload()

    def _prune(self) -> None:
        now = time.time()
        self.entries = {
            key: entry
            for key, entry in self.entries.items()
            if (entry.task and not entry.task.done()) or entry.job.expires_at > now
        }

    def check_runtime(self, runtime_id: str) -> None:
        if self.closed or runtime_id != self.runtime_id:
            raise ASRError("runtime_changed", 409)

    def _check_request(self, request_id: str) -> float:
        match = _ID.fullmatch(request_id)
        issued = int(match[1]) / 1000 if match else 0
        if not match or not time.time() - REQUEST_TTL <= issued <= time.time() + 5:
            raise ASRError("request_expired", 409)
        return issued

    def local_in_use(self, model_id: str | None = None) -> bool:
        return any(
            entry.options
            and entry.options.mode == "local"
            and (model_id is None or entry.options.model == model_id)
            and entry.task
            and not entry.task.done()
            for entry in self.entries.values()
        )

    def revision(self, config: AppConfig | None = None) -> str:
        config = config or self.config()
        settings = config.speech.asr
        provider = (
            config.llm.providers.get(settings.provider_id) if settings.mode == "remote" else None
        )
        source = {"runtime": self.runtime_id, "asr": settings.model_dump(mode="json")}
        if provider is not None:
            source["proxy_url"] = config.network.proxy_url()
            source["provider"] = {
                "enabled": provider.enabled,
                "type": provider.provider_type.value,
                "name": provider.display_name,
                "base_url": provider.base_url,
                "api_key": provider.api_key,
                "service": provider.services.asr.model_dump(mode="json"),
            }
        return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()

    async def status(self) -> ASRStatus:
        config = self.config()
        settings = config.speech.asr
        result = ASRStatus(
            config_revision=self.revision(config),
            runtime_id=self.runtime_id,
            enabled=settings.enabled,
            mode=settings.mode,
            ready=False,
        )
        try:
            options = resolve_options(config)
            result.provider_name, result.model = options.provider_name, options.model
            if options.mode == "local":
                if importlib.util.find_spec("sherpa_onnx") is None:
                    raise ASRError("runtime_unavailable", 503)
                if not await self.models.ready(options.model):
                    raise ASRError("model_not_ready", 409)
            result.ready = True
        except ASRError as exc:
            result.error = exc.code
        return result

    async def submit(
        self, owner: str, runtime_id: str, request_id: str, audio: bytes, *, config_revision: str
    ) -> ASRJob:
        self.check_runtime(runtime_id)
        issued = self._check_request(request_id)
        if len(audio) > MAX_AUDIO_BYTES:
            raise ASRError("audio_too_large", 413)
        try:
            info = inspect_wav(audio)
        except ValueError as exc:
            raise ASRError("invalid_audio", 422) from exc
        if info.sample_rate_hz != 16000 or info.channels != 1:
            raise ASRError("invalid_audio", 422)
        fingerprint = hashlib.sha256(audio).hexdigest()
        async with self.admission:
            self.check_runtime(runtime_id)
            self._prune()
            entry = self.entries.get((owner, request_id))
            if entry:
                if entry.fingerprint is not None and entry.fingerprint != fingerprint:
                    raise ASRError("request_conflict", 409)
                return entry.job.model_copy(deep=True)
            active = sum(bool(item.task and not item.task.done()) for item in self.entries.values())
            if active >= MAX_ACTIVE or len(self.entries) >= MAX_RECEIPTS:
                raise ASRError("engine_busy", 429)
            config = self.config()
            if config_revision != self.revision(config):
                raise ASRError("configuration_changed", 409)
            options = resolve_options(config)
            if options.mode == "local" and not await self.models.ready(options.model):
                raise ASRError("model_not_ready", 409)
            self.check_runtime(runtime_id)
            # Model verification yields: cancellation may have claimed this identity.
            entry = self.entries.get((owner, request_id))
            if entry is not None:
                return entry.job.model_copy(deep=True)
            if len(self.entries) >= MAX_RECEIPTS:
                raise ASRError("engine_busy", 429)
            job = ASRJob(
                request_id=request_id,
                runtime_id=self.runtime_id,
                state="queued",
                expires_at=max(time.time(), issued) + REQUEST_TTL + RESULT_TTL,
            )
            entry = _Entry(job, fingerprint, options, audio)
            self.entries[(owner, request_id)] = entry
            entry.task = asyncio.create_task(self._run(entry, options))
            self._maintain()
            return job.model_copy(deep=True)

    def get(self, owner: str, runtime_id: str, request_id: str) -> ASRJob:
        self.check_runtime(runtime_id)
        self._prune()
        entry = self.entries.get((owner, request_id))
        if entry is None:
            raise ASRError("request_not_found", 404)
        return entry.job.model_copy(deep=True)

    def cancel(self, owner: str, runtime_id: str, request_id: str) -> ASRJob:
        self.check_runtime(runtime_id)
        self._prune()
        entry = self.entries.get((owner, request_id))
        if entry is None:
            issued = self._check_request(request_id)
            if len(self.entries) >= MAX_RECEIPTS:
                raise ASRError("engine_busy", 429)
            # A cancellation can arrive before its upload. This tombstone wins.
            entry = _Entry(
                ASRJob(
                    request_id=request_id,
                    runtime_id=self.runtime_id,
                    state="cancelled",
                    expires_at=issued + REQUEST_TTL + RESULT_TTL,
                ),
                None,
            )
            self.entries[(owner, request_id)] = entry
        entry.cancel.set()
        entry.audio = b""
        entry.job.state, entry.job.result, entry.job.error = "cancelled", None, "cancelled"
        self._maintain()
        return entry.job.model_copy(deep=True)

    async def _run(self, entry: _Entry, options: ASROptions) -> None:
        try:
            async with self.compute:
                if entry.cancel.is_set():
                    return
                entry.job.state = "running"
                if options.mode == "local":
                    operation = asyncio.create_task(
                        asyncio.to_thread(
                            self.local.transcribe,
                            entry.audio,
                            self.models.get(options.model).directory,
                            options,
                        )
                    )
                else:
                    operation = asyncio.create_task(remote_transcribe(entry.audio, options))
                cancelled = asyncio.create_task(entry.cancel.wait())
                try:
                    done, _ = await asyncio.wait(
                        {operation, cancelled},
                        timeout=options.timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if operation in done and not entry.cancel.is_set():
                        entry.job.result = operation.result()
                        entry.job.state = "succeeded"
                    elif not entry.cancel.is_set():
                        entry.job.state, entry.job.error = (
                            "failed",
                            ("provider_timeout" if options.mode == "remote" else "engine_timeout"),
                        )
                    if not operation.done() and options.mode == "remote":
                        operation.cancel()
                    # A native call cannot be interrupted by cancelling an asyncio future.
                    # Keep this permit and the model lease until the actual call finishes.
                    await asyncio.gather(operation, return_exceptions=True)
                finally:
                    cancelled.cancel()
                    await asyncio.gather(cancelled, return_exceptions=True)
                    self.last_local_use = time.monotonic()
        except ASRError as exc:
            entry.job.state, entry.job.error = "failed", exc.code
        except Exception:
            entry.job.state, entry.job.error = "failed", "engine_failed"
        finally:
            if entry.cancel.is_set():
                entry.job.state, entry.job.result, entry.job.error = "cancelled", None, "cancelled"
            entry.job.expires_at = max(entry.job.expires_at, time.time() + RESULT_TTL)
            entry.options = None
            entry.audio = b""

    async def clear(self) -> dict[str, int]:
        async with self.admission:
            self.runtime_id = uuid.uuid4().hex
            count = len(self.entries)
            for entry in self.entries.values():
                entry.cancel.set()
                entry.job.state, entry.job.result, entry.job.error = "cancelled", None, "cancelled"
            await asyncio.gather(
                *(entry.task for entry in self.entries.values() if entry.task),
                return_exceptions=True,
            )
            self.entries.clear()
            return {"asr_jobs": count}

    async def close(self) -> None:
        await self.clear()
        self.closed = True
        await self.models.cancel_all()
        if self.maintenance:
            self.maintenance.cancel()
            await asyncio.gather(self.maintenance, return_exceptions=True)
        await asyncio.gather(
            *(entry.task for entry in self.entries.values() if entry.task), return_exceptions=True
        )
        self.entries.clear()
        self.local.unload()


_service: ASRService | None = None


def get_asr_service() -> ASRService:
    global _service
    if _service is None:
        _service = ASRService(ASRModelStore(RuntimePaths().models_cache_dir / "asr"))
    return _service


async def clear_asr_content() -> dict[str, int]:
    return await _service.clear() if _service else {"asr_jobs": 0}


async def close_asr_service() -> None:
    global _service
    if _service:
        await _service.close()
        _service = None
