from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

import pytest

from magi.core.chat_assets.mutations import run_chat_asset_mutation
from magi.core.chat_assets.io import (
    aopen_managed_chat_attachment,
    open_managed_chat_attachment,
    stream_managed_chat_file,
)
from magi.chat.attachment_storage import LocalChatAttachmentStorage
from magi.utils.runtime import RuntimePaths


R = TypeVar("R")


def _mutate(func: Callable[..., R], **kwargs: Any) -> R:
    return asyncio.run(run_chat_asset_mutation(func, **kwargs))


def test_store_image_attachment_writes_to_managed_image_directory(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / ".magi")
    storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)

    stored = _mutate(
        storage.store_image_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="diagram.png",
        content=b"image-bytes",
        mime_type="image/png",
    )

    stored_path = Path(stored.storage_path)

    assert stored.kind == "image"
    assert stored.original_name == "diagram.png"
    assert stored.mime_type == "image/png"
    assert stored.size_bytes == len(b"image-bytes")
    assert stored.sha256 == hashlib.sha256(b"image-bytes").hexdigest()
    assert (
        stored_path.parent
        == runtime_paths.data_dir / "resources" / "chat" / "images" / "session-1" / "turn-1"
    )
    assert stored_path.read_bytes() == b"image-bytes"


def test_store_file_attachment_writes_to_managed_file_directory_and_sanitizes_name(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / ".magi")
    storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)

    stored = _mutate(
        storage.store_file_attachment,
        session_id="session-1",
        turn_id="turn-2",
        original_name="../notes.md",
        content=b"# notes",
        mime_type="text/markdown",
    )

    stored_path = Path(stored.storage_path)

    assert stored.kind == "file"
    assert stored.original_name == "notes.md"
    assert stored.mime_type == "text/markdown"
    assert stored.size_bytes == len(b"# notes")
    assert stored.sha256 == hashlib.sha256(b"# notes").hexdigest()
    assert (
        stored_path.parent
        == runtime_paths.data_dir / "resources" / "chat" / "files" / "session-1" / "turn-2"
    )
    assert stored_path.name.endswith("__notes.md")
    assert stored_path.read_bytes() == b"# notes"


@pytest.mark.parametrize(
    ("field_name", "unsafe_value"),
    [
        ("session_id", ""),
        ("session_id", "."),
        ("session_id", ".."),
        ("session_id", "a/b"),
        ("turn_id", "."),
        ("turn_id", ".."),
        ("turn_id", "a\\b"),
    ],
)
def test_store_attachment_rejects_unsafe_path_components(
    tmp_path: Path,
    field_name: str,
    unsafe_value: str,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / ".magi")
    storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)
    kwargs = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "original_name": "notes.txt",
        "content": b"private",
        "mime_type": "text/plain",
    }
    kwargs[field_name] = unsafe_value

    with pytest.raises(ValueError):
        _mutate(storage.store_file_attachment, **kwargs)

    assert not list(runtime_paths.chat_files_dir.rglob("*"))


def test_store_attachment_rejects_retargeted_asset_root(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / ".magi")
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime_paths.chat_files_dir.symlink_to(outside, target_is_directory=True)
    storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)

    with pytest.raises(ValueError, match="outside chat resources"):
        _mutate(
            storage.store_file_attachment,
            session_id="session-1",
            turn_id="turn-1",
            original_name="notes.txt",
            content=b"private",
            mime_type="text/plain",
        )

    assert not list(outside.rglob("*"))


@pytest.mark.skipif(os.name == "nt", reason="Symlink race requires Unix symlink support")
def test_safe_attachment_open_rejects_file_replaced_by_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.core.chat_assets import io as asset_io

    runtime_paths = RuntimePaths(tmp_path / ".magi")
    stored = _mutate(
        LocalChatAttachmentStorage(
            runtime_paths=runtime_paths,
        ).store_file_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="notes.txt",
        content=b"managed",
        mime_type="text/plain",
    )
    stored_path = Path(stored.storage_path)
    private_path = runtime_paths.base_dir / "private.txt"
    private_path.write_bytes(b"private")
    original_open = asset_io.os.open
    replaced = False

    def replace_before_open(path, flags):
        nonlocal replaced
        if Path(path) == stored_path and not replaced:
            replaced = True
            stored_path.unlink()
            stored_path.symlink_to(private_path)
        return original_open(path, flags)

    monkeypatch.setattr(asset_io.os, "open", replace_before_open)

    handle = open_managed_chat_attachment(
        stored_path,
        session_id="session-1",
        turn_id="turn-1",
        attachment_id=stored.attachment_id,
        original_name=stored.original_name,
        runtime_paths=runtime_paths,
    )

    assert replaced is True
    assert handle is None


@pytest.mark.skipif(os.name == "nt", reason="Symlink race requires Unix symlink support")
def test_safe_attachment_open_rejects_parent_replaced_by_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.core.chat_assets import io as asset_io

    runtime_paths = RuntimePaths(tmp_path / ".magi")
    stored = _mutate(
        LocalChatAttachmentStorage(
            runtime_paths=runtime_paths,
        ).store_file_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="notes.txt",
        content=b"managed",
        mime_type="text/plain",
    )
    stored_path = Path(stored.storage_path)
    turn_dir = stored_path.parent
    original_turn_dir = turn_dir.with_name("turn-1-original")
    polluted_turn_dir = runtime_paths.base_dir / "polluted-turn"
    polluted_turn_dir.mkdir()
    (polluted_turn_dir / stored_path.name).write_bytes(b"private")
    original_open = asset_io.os.open
    replaced = False

    def replace_before_open(path, flags):
        nonlocal replaced
        if Path(path) == stored_path and not replaced:
            replaced = True
            turn_dir.rename(original_turn_dir)
            turn_dir.symlink_to(polluted_turn_dir, target_is_directory=True)
        return original_open(path, flags)

    monkeypatch.setattr(asset_io.os, "open", replace_before_open)

    handle = open_managed_chat_attachment(
        stored_path,
        session_id="session-1",
        turn_id="turn-1",
        attachment_id=stored.attachment_id,
        original_name=stored.original_name,
        runtime_paths=runtime_paths,
    )

    assert replaced is True
    assert handle is None


@pytest.mark.asyncio
async def test_cancelled_safe_attachment_open_closes_late_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.core.chat_assets import io as asset_io

    open_started = threading.Event()
    release_open = threading.Event()
    read_descriptor, write_descriptor = os.pipe()
    late_handle = os.fdopen(read_descriptor, "rb", closefd=True)

    def blocking_open(*_args, **_kwargs):
        open_started.set()
        assert release_open.wait(2)
        return late_handle

    monkeypatch.setattr(asset_io, "open_managed_chat_attachment", blocking_open)
    opening = asyncio.create_task(
        aopen_managed_chat_attachment(
            tmp_path / "staged",
            session_id="session-1",
            turn_id="turn-1",
            attachment_id="attachment-1",
        )
    )
    try:
        assert await asyncio.to_thread(open_started.wait, 2)
        opening.cancel()
        await asyncio.sleep(0.05)
        assert not opening.done()

        release_open.set()
        with pytest.raises(asyncio.CancelledError):
            await opening
        assert late_handle.closed
    finally:
        release_open.set()
        late_handle.close()
        os.close(write_descriptor)


@pytest.mark.asyncio
async def test_cancelled_attachment_stream_waits_for_read_then_closes_handle() -> None:
    class _BlockingHandle:
        def __init__(self) -> None:
            self.read_started = threading.Event()
            self.release_read = threading.Event()
            self.closed = False

        def read(self, _size: int) -> bytes:
            self.read_started.set()
            assert self.release_read.wait(2)
            return b""

        def close(self) -> None:
            self.closed = True

    handle = _BlockingHandle()
    stream = stream_managed_chat_file(handle)  # type: ignore[arg-type]
    reading = asyncio.create_task(anext(stream))
    assert await asyncio.to_thread(handle.read_started.wait, 2)

    reading.cancel()
    await asyncio.sleep(0.05)
    assert not reading.done()

    handle.release_read.set()
    with pytest.raises(asyncio.CancelledError):
        await reading
    assert handle.closed


@pytest.mark.parametrize(
    ("session_id", "turn_id"),
    [
        ("session-1", "Turn-2"),
        ("Session-1", "turn-1"),
    ],
)
def test_store_attachment_rejects_casefold_scope_aliases(
    tmp_path: Path,
    session_id: str,
    turn_id: str,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / ".magi")
    storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)
    original = _mutate(
        storage.store_file_attachment,
        session_id="Session-1",
        turn_id="Turn-1",
        original_name="original.txt",
        content=b"original",
        mime_type="text/plain",
    )

    with pytest.raises(ValueError, match="scope is ambiguous"):
        _mutate(
            storage.store_file_attachment,
            session_id=session_id,
            turn_id=turn_id,
            original_name="alias.txt",
            content=b"alias",
            mime_type="text/plain",
        )

    assert Path(original.storage_path).read_bytes() == b"original"
