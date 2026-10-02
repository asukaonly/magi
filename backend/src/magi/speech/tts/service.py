"""TTS-only receipts, resource expiry, cancellation and pull-driven synthesis."""

import asyncio
import hashlib
import json
import shutil
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import httpx
from magi_plugin_sdk.audio import AudioClip

from .contracts import MessageSource, SynthesisJob, SynthesisRequest
from .engines import EngineOptions, TTSEngine
from .models import ModelManager
from .text import clean_segments

SOURCE_TTL = 600
RECEIPT_TTL = 86400
MAX_RECEIPTS = 128
MAX_AUDIO_STORAGE = 64 * 1024 * 1024


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class Receipt:
    owner: str
    identity: str
    job: SynthesisJob
    source: MessageSource | None = None
    segments: list[str] = field(default_factory=list)
    options: EngineOptions | None = None
    cancellation: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task[None] | None = None


class SynthesisService:
    def __init__(self, root: Path, models: ModelManager,
                 read_message: Callable[[MessageSource], Awaitable[str]]) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.models = models
        self.engine = TTSEngine(models)
        self.read_message = read_message
        self.receipts: dict[str, Receipt] = {}
        self.sealed = False
        self.epoch = 0
        self._admission = asyncio.Lock()
        for path in root.glob("*/receipt.json"):
            payload = json.loads(path.read_text())
            job = SynthesisJob.model_validate(payload["job"])
            if job.state in {"running", "cancelling", "ready"}:
                job.state, job.error = "unknown", "interrupted"
            receipt = Receipt(payload["owner"], payload["identity"], job,
                              MessageSource.model_validate(payload["source"]) if payload.get("source") else None)
            self.receipts[job.job_id] = receipt
            self._save(receipt)
        self._expire()

    def _save(self, receipt: Receipt) -> None:
        directory = self.root / receipt.job.job_id
        directory.mkdir(exist_ok=True, mode=0o700)
        payload = {"owner": receipt.owner, "identity": receipt.identity, "job": receipt.job.model_dump(),
                   "source": receipt.source.model_dump() if receipt.source else None}
        temporary = directory / "receipt.tmp"
        temporary.write_text(json.dumps(payload))
        temporary.replace(directory / "receipt.json")

    def _expire(self) -> None:
        now = time.time()
        for key, receipt in list(self.receipts.items()):
            if now > receipt.job.expires_at:
                receipt.cancellation.set()
                if receipt.job.state == "ready":
                    receipt.job.state, receipt.job.error = "cancelled", "audio_expired"
                    self._save(receipt)
                receipt.segments.clear()
                receipt.options = None
                for path in (self.root / key).glob("*.wav"):
                    path.unlink(missing_ok=True)
            if now > receipt.job.expires_at + RECEIPT_TTL and not (receipt.task and not receipt.task.done()):
                shutil.rmtree(self.root / key, ignore_errors=True)
                del self.receipts[key]

    async def create(self, owner: str, request: SynthesisRequest, options: EngineOptions) -> SynthesisJob:
        async with self._admission:
            if self.sealed:
                raise ValueError("content_clearing")
            self._expire()
            identity = fingerprint(request.source.model_dump())
            for receipt in self.receipts.values():
                if receipt.owner == owner and receipt.job.request_id == str(request.request_id):
                    if receipt.identity not in {identity, "cancelled"}:
                        raise ValueError("request_conflict")
                    return receipt.job.model_copy()
            if len(self.receipts) >= MAX_RECEIPTS:
                raise ValueError("capacity_exceeded")
            epoch = self.epoch
            text = request.source.text if request.source.kind == "text" else await self.read_message(request.source)
            if epoch != self.epoch or self.sealed:
                raise ValueError("content_clearing")
            segments = clean_segments(text)
            job = SynthesisJob(job_id=str(uuid4()), request_id=str(request.request_id), state="ready",
                               engine=options.engine, model=options.model, voice=options.voice, speed=options.speed,
                               content_hash=fingerprint({"text": segments, "options": asdict(options), "cleaner": "1"}),
                               total_segments=len(segments), expires_at=time.time() + SOURCE_TTL)
            receipt = Receipt(owner, identity, job, request.source if request.source.kind == "message" else None,
                              segments, options)
            self._save(receipt)
            self.receipts[job.job_id] = receipt
            return job.model_copy()

    def owned(self, owner: str, job_id: str) -> Receipt:
        self._expire()
        receipt = self.receipts.get(job_id)
        if not receipt or receipt.owner != owner:
            raise ValueError("not_found")
        return receipt

    async def validate_source(self, receipt: Receipt) -> None:
        self._require_current(receipt)
        if receipt.source:
            try:
                await self.read_message(receipt.source)
            except ValueError:
                self._require_current(receipt)
                self.cancel(receipt.owner, receipt.job.job_id)
                for path in (self.root / receipt.job.job_id).glob("*.wav"):
                    path.unlink(missing_ok=True)
                raise
        self._require_current(receipt)

    def _require_current(self, receipt: Receipt) -> None:
        if self.sealed or self.receipts.get(receipt.job.job_id) is not receipt:
            raise ValueError("content_clearing")

    async def get(self, owner: str, job_id: str) -> SynthesisJob:
        receipt = self.owned(owner, job_id)
        await self.validate_source(receipt)
        return receipt.job.model_copy()

    async def by_request(self, owner: str, request_id: str) -> SynthesisJob:
        for receipt in self.receipts.values():
            if receipt.owner == owner and receipt.job.request_id == request_id:
                return await self.get(owner, receipt.job.job_id)
        raise ValueError("not_found")

    async def advance(self, owner: str, job_id: str, seq: int) -> SynthesisJob:
        receipt = self.owned(owner, job_id)
        await self.validate_source(receipt)
        job = receipt.job
        if time.time() >= job.expires_at:
            raise ValueError("audio_expired")
        if seq < job.ready_segments:
            return job.model_copy()
        if seq != job.ready_segments or seq >= job.total_segments:
            raise ValueError("sequence_error")
        if job.state == "running":
            return job.model_copy()
        if job.state != "ready" or self.sealed or receipt.cancellation.is_set():
            raise ValueError("synthesis_closed")
        if sum(bool(r.task and not r.task.done()) for r in self.receipts.values()) >= 4:
            raise ValueError("capacity_exceeded")
        job.state = "running"
        self._save(receipt)
        receipt.task = asyncio.create_task(self._run(receipt, seq, self.epoch))
        epoch = self.epoch
        def settled(task: asyncio.Task[None]) -> None:
            if task.cancelled() and epoch == self.epoch:
                receipt.job.state = "cancelled"
                receipt.job.error = "cancelled"
                self._save(receipt)
        receipt.task.add_done_callback(settled)
        return job.model_copy()

    async def _run(self, receipt: Receipt, seq: int, epoch: int) -> None:
        job = receipt.job
        try:
            options = receipt.options
            if not options:
                raise ValueError("interrupted")
            clip = await self.engine.synthesize(receipt.segments[seq], options, receipt.cancellation)
            await self.validate_source(receipt)
            if receipt.cancellation.is_set() or epoch != self.epoch or time.time() >= job.expires_at:
                raise ValueError("cancelled")
            used = sum(path.stat().st_size for path in self.root.glob("*/*.wav"))
            if used + len(clip.data) > MAX_AUDIO_STORAGE:
                raise ValueError("capacity_exceeded")
            (self.root / job.job_id / f"{seq}.wav").write_bytes(clip.data)
            job.ready_segments += 1
            job.state = "completed" if job.ready_segments == job.total_segments else "ready"
        except asyncio.CancelledError:
            job.state, job.error = "cancelled", "cancelled"
        except (httpx.HTTPError, asyncio.TimeoutError):
            job.state, job.error = "unknown", "provider_outcome_unknown"
        except Exception as exc:
            allowed = {"runtime_missing", "model_missing", "model_checksum_failed", "model_invalid", "cancelled",
                       "provider_rejected", "audio_too_large", "capacity_exceeded", "stale_message", "interrupted"}
            job.state = "cancelled" if receipt.cancellation.is_set() else "failed"
            job.error = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else "synthesis_failed"
        finally:
            if epoch == self.epoch:
                self._save(receipt)

    def cancel(self, owner: str, job_id: str) -> SynthesisJob:
        receipt = self.owned(owner, job_id)
        receipt.cancellation.set()
        active = receipt.task is not None and not receipt.task.done()
        receipt.job.state = "cancelling" if active else "cancelled"
        if active and receipt.job.engine == "remote":
            receipt.task.cancel()
        if not active:
            receipt.segments.clear()
            receipt.options = None
        self._save(receipt)
        return receipt.job.model_copy()

    async def cancel_request(self, owner: str, request_id: str) -> SynthesisJob:
        async with self._admission:
            if self.sealed:
                raise ValueError("content_clearing")
            for receipt in self.receipts.values():
                if receipt.owner == owner and receipt.job.request_id == request_id:
                    return self.cancel(owner, receipt.job.job_id)
            self._expire()
            if len(self.receipts) >= MAX_RECEIPTS:
                raise ValueError("capacity_exceeded")
            job = SynthesisJob(job_id=str(uuid4()), request_id=request_id, state="cancelled", engine="",
                               model="", voice="", speed=1, content_hash="", total_segments=0,
                               expires_at=time.time() + SOURCE_TTL)
            receipt = Receipt(owner, "cancelled", job)
            receipt.cancellation.set()
            self._save(receipt)
            self.receipts[job.job_id] = receipt
            return job.model_copy()

    async def segment(self, owner: str, job_id: str, seq: int) -> AudioClip:
        receipt = self.owned(owner, job_id)
        await self.validate_source(receipt)
        if time.time() >= receipt.job.expires_at:
            raise ValueError("audio_expired")
        if receipt.cancellation.is_set():
            raise ValueError("synthesis_closed")
        if not 0 <= seq < receipt.job.ready_segments:
            raise ValueError("not_found")
        return AudioClip(data=(self.root / job_id / f"{seq}.wav").read_bytes())

    @asynccontextmanager
    async def clear_boundary(self) -> AsyncIterator[None]:
        self.sealed = True
        self.epoch += 1
        try:
            for receipt in list(self.receipts.values()):
                receipt.cancellation.set()
                receipt.segments.clear()
                receipt.options = None
                if receipt.task and receipt.job.engine == "remote":
                    receipt.task.cancel()
            self.receipts.clear()
            for directory in self.root.iterdir():
                if directory.is_dir():
                    shutil.rmtree(directory)
            yield
        finally:
            self.sealed = False
