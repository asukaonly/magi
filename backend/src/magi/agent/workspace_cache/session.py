"""Per-session cache facade."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .atomic_io import append_jsonl
from .contracts import EditOp, EditRecord, ReadRecord
from .errors import SessionCacheCorruptError
from .root import WorkspaceCacheRoot


_HASH_BUF = 1 << 20  # 1 MiB


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sha256_file(path: Path) -> tuple[str, int, int]:
    """Return (sha256_hex, size_bytes, line_count) for ``path``."""
    h = hashlib.sha256()
    size = 0
    line_count = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_HASH_BUF)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
            line_count += chunk.count(b"\n")
    return h.hexdigest(), size, line_count


def _relative_posix(workspace: Path, target: Path) -> str:
    workspace_resolved = workspace.resolve()
    parent = target.parent.resolve()
    candidate = parent / target.name
    try:
        return candidate.relative_to(workspace_resolved).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside workspace_root: {target}") from exc


@dataclass
class SessionCache:
    root: WorkspaceCacheRoot
    session_id: str

    @property
    def session_dir(self) -> Path:
        d = self.root.session_dir_for(self.session_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def reads_log(self) -> Path:
        return self.session_dir / "reads.jsonl"

    def record_read(self, path: str | Path) -> ReadRecord:
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(target)
        rel = _relative_posix(self.root.workspace_root, target)
        sha, size, lc = _sha256_file(target)
        rec = ReadRecord(
            path=rel,
            sha256=sha,
            size_bytes=size,
            line_count=lc,
            mtime_ms=int(target.stat().st_mtime * 1000),
            ts_ms=_now_ms(),
        )
        append_jsonl(self.reads_log, rec.model_dump())
        return rec

    def has_read(self, path: str | Path) -> bool:
        target = Path(path)
        if not target.exists():
            return False
        try:
            rel = _relative_posix(self.root.workspace_root, target)
        except ValueError:
            return False
        sha, _, _ = _sha256_file(target)
        for rec in self.iter_reads():
            if rec.path == rel and rec.sha256 == sha:
                return True
        return False

    def iter_reads(self) -> Iterator[ReadRecord]:
        log = self.reads_log
        if not log.exists():
            return
        with open(log, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SessionCacheCorruptError(
                        f"reads.jsonl line {line_no} is not valid JSON"
                    ) from exc
                yield ReadRecord.model_validate(payload)

    @property
    def edits_log(self) -> Path:
        return self.session_dir / "edits.jsonl"

    def record_edit(
        self,
        *,
        path: str | Path,
        op: EditOp,
        sha256_before: str,
        sha256_after: str,
        snapshot_ref: str,
    ) -> EditRecord:
        target = Path(path)
        rel = _relative_posix(self.root.workspace_root, target)
        rec = EditRecord(
            path=rel,
            op=op,
            sha256_before=sha256_before,
            sha256_after=sha256_after,
            snapshot_ref=snapshot_ref,
            ts_ms=_now_ms(),
        )
        append_jsonl(self.edits_log, rec.model_dump())
        return rec

    def iter_edits(self) -> Iterator[EditRecord]:
        log = self.edits_log
        if not log.exists():
            return
        with open(log, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SessionCacheCorruptError(
                        f"edits.jsonl line {line_no} is not valid JSON"
                    ) from exc
                yield EditRecord.model_validate(payload)
