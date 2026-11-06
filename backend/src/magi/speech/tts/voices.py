"""Bounded, private reference WAVs for model-specific voice recipes."""

import hashlib
import os
import tempfile
import re
from pathlib import Path

from magi_plugin_sdk.audio import inspect_wav

from .contracts import TTSReferenceAudio


class TTSReferenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)

    def list(self) -> list[TTSReferenceAudio]:
        result = []
        for path in sorted(self.root.glob("*.json")):
            try:
                if path.is_symlink() or path.stat().st_size > 4096:
                    continue
                item = TTSReferenceAudio.model_validate_json(path.read_text())
                if path.stem == item.id and re.fullmatch(r"[a-f0-9]{64}", item.id):
                    result.append(item)
            except (OSError, ValueError):
                continue
        return result

    def add(self, data: bytes, name: str) -> TTSReferenceAudio:
        try:
            info = inspect_wav(data)
            if not 3 <= info.duration_seconds <= 20:
                raise ValueError("Invalid duration")
        except ValueError as exc:
            raise ValueError("reference_audio_invalid") from exc
        identity = hashlib.sha256(data).hexdigest()
        if not (self.root / (identity + ".wav")).exists() and sum(1 for _ in self.root.glob("*.wav")) >= 32:
            raise ValueError("reference_audio_full")
        result = TTSReferenceAudio(id=identity, name=name[:120], seconds=info.duration_seconds)
        self._write(identity + ".wav", data)
        self._write(identity + ".json", result.model_dump_json().encode())
        return result

    def _write(self, name: str, data: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".upload-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.root / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def path(self, identity: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("reference_audio_missing")
        path = self.root / (identity + ".wav")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("reference_audio_missing")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != identity:
            raise ValueError("reference_audio_invalid")
        inspect_wav(data)
        return path

    def delete(self, identity: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("reference_audio_missing")
        # Removal is also the repair path for missing or corrupted recordings.
        path = self.root / (identity + ".wav")
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)
