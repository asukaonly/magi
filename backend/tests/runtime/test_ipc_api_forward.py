"""Tests for the api.forward IPC handler — ASGI dispatch round-trip."""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import threading
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response

from magi.ipc.handlers import ApiForwardHandler
from magi.ipc import handlers as ipc_handlers


def _write_secure_staged_body(content: bytes) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix="magi-ipc-body-",
        delete=False,
    ) as handle:
        handle.write(content)
        return Path(handle.name)


@pytest.fixture
def sample_app() -> FastAPI:
    """Minimal FastAPI app for testing the forward handler."""
    app = FastAPI()

    @app.get("/api/echo")
    async def echo_get():
        return {"method": "GET", "ok": True}

    @app.post("/api/echo")
    async def echo_post(data: dict | None = None):
        return {"method": "POST", "body": data, "ok": True}

    @app.post("/api/raw")
    async def raw_post(request: Request):
        payload = await request.body()
        return {
            "content_type": request.headers.get("content-type"),
            "body_base64": base64.b64encode(payload).decode("ascii"),
            "size": len(payload),
        }

    @app.post("/api/raw-stream")
    async def raw_stream_post(request: Request):
        chunk_sizes = [len(chunk) async for chunk in request.stream() if chunk]
        return {
            "chunk_sizes": chunk_sizes,
            "size": sum(chunk_sizes),
        }

    @app.get("/api/with-query")
    async def with_query(foo: str = "default"):
        return {"foo": foo}

    @app.delete("/api/items/{item_id}")
    async def delete_item(item_id: str):
        return {"deleted": item_id}

    @app.get("/api/file")
    async def file_content():
        return Response(content=b"\x89PNG\r\n", media_type="image/png")

    return app


@pytest.fixture
def forward_handler(sample_app: FastAPI) -> ApiForwardHandler:
    return ApiForwardHandler(sample_app)


class TestApiForwardHandler:
    @pytest.mark.asyncio
    async def test_get_request(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle(
            {
                "method": "GET",
                "path": "/api/echo",
            }
        )
        assert result["status"] == 200
        assert result["body"]["method"] == "GET"
        assert result["body"]["ok"] is True

    @pytest.mark.asyncio
    async def test_post_with_body(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle(
            {
                "method": "POST",
                "path": "/api/echo",
                "body": {"key": "value"},
            }
        )
        assert result["status"] == 200
        assert result["body"]["method"] == "POST"
        assert result["body"]["body"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_post_with_staged_body_file(self, forward_handler: ApiForwardHandler) -> None:
        payload = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="image.png"\r\nContent-Type: image/png\r\n\r\n\x89PNG\r\n\x1a\n\r\n--boundary--\r\n'
        staged_path = _write_secure_staged_body(payload)
        try:
            result = await forward_handler.handle(
                {
                    "method": "POST",
                    "path": "/api/raw",
                    "headers": {"content-type": "multipart/form-data; boundary=boundary"},
                    "body_file_path": str(staged_path),
                }
            )
        finally:
            staged_path.unlink(missing_ok=True)

        assert result["status"] == 200
        assert result["body"]["content_type"] == "multipart/form-data; boundary=boundary"
        assert result["body"]["size"] == len(payload)
        assert result["body"]["body_base64"] == base64.b64encode(payload).decode("ascii")

    @pytest.mark.asyncio
    async def test_staged_body_file_is_forwarded_in_bounded_chunks(
        self,
        forward_handler: ApiForwardHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        payload = b"x" * (2 * 1024 * 1024 + 17)
        staged_path = _write_secure_staged_body(payload)
        original_read_bytes = Path.read_bytes

        def reject_full_read(path: Path) -> bytes:
            if path == staged_path:
                raise AssertionError("staged request body must not be read all at once")
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", reject_full_read)

        try:
            result = await forward_handler.handle(
                {
                    "method": "POST",
                    "path": "/api/raw-stream",
                    "headers": {"content-type": "application/octet-stream"},
                    "body_file_path": str(staged_path),
                }
            )
        finally:
            staged_path.unlink(missing_ok=True)

        assert result["status"] == 200
        assert result["body"]["size"] == len(payload)
        assert result["body"]["chunk_sizes"] == [
            1024 * 1024,
            1024 * 1024,
            17,
        ]

    @pytest.mark.asyncio
    async def test_staged_body_rejects_path_outside_temp_boundary(
        self,
        forward_handler: ApiForwardHandler,
        tmp_path: Path,
    ) -> None:
        outside = tmp_path / "magi-ipc-body-untrusted"
        outside.write_bytes(b"private")
        outside.chmod(0o600)

        result = await forward_handler.handle(
            {
                "method": "POST",
                "path": "/api/raw",
                "body_file_path": str(outside),
            }
        )

        assert result["status"] == 400
        assert "outside the IPC staging boundary" in result["body"]["detail"]

    @pytest.mark.asyncio
    async def test_staged_body_rejects_symlink(
        self,
        forward_handler: ApiForwardHandler,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "private.txt"
        target.write_bytes(b"private")
        staged_path = Path(tempfile.gettempdir()) / f"magi-ipc-body-symlink-{uuid.uuid4().hex}"
        staged_path.unlink(missing_ok=True)
        try:
            staged_path.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks are not available on this platform")
        try:
            result = await forward_handler.handle(
                {
                    "method": "POST",
                    "path": "/api/raw",
                    "body_file_path": str(staged_path),
                }
            )
        finally:
            staged_path.unlink(missing_ok=True)

        assert result["status"] == 400
        assert "outside the IPC staging boundary" in result["body"]["detail"]

    @pytest.mark.asyncio
    async def test_staged_body_rejects_oversized_sparse_file(
        self,
        forward_handler: ApiForwardHandler,
    ) -> None:
        staged_path = _write_secure_staged_body(b"")
        try:
            with staged_path.open("r+b") as handle:
                handle.truncate(55 * 1024 * 1024 + 1)
            result = await forward_handler.handle(
                {
                    "method": "POST",
                    "path": "/api/raw",
                    "body_file_path": str(staged_path),
                }
            )
        finally:
            staged_path.unlink(missing_ok=True)

        assert result["status"] == 400
        assert "exceeds the forwarding limit" in result["body"]["detail"]

    @pytest.mark.skipif(os.name == "nt", reason="Unix permission bits are required")
    @pytest.mark.asyncio
    async def test_staged_body_rejects_broad_permissions(
        self,
        forward_handler: ApiForwardHandler,
    ) -> None:
        staged_path = _write_secure_staged_body(b"private")
        staged_path.chmod(0o644)
        try:
            result = await forward_handler.handle(
                {
                    "method": "POST",
                    "path": "/api/raw",
                    "body_file_path": str(staged_path),
                }
            )
        finally:
            staged_path.unlink(missing_ok=True)

        assert result["status"] == 400
        assert "permissions are too broad" in result["body"]["detail"]

    @pytest.mark.asyncio
    async def test_staged_body_rejects_hard_link(
        self,
        forward_handler: ApiForwardHandler,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "private.txt"
        target.write_bytes(b"private")
        target.chmod(0o600)
        staged_path = Path(tempfile.gettempdir()) / f"magi-ipc-body-hard-link-{uuid.uuid4().hex}"
        try:
            os.link(target, staged_path)
        except OSError:
            pytest.skip("Hard links are not available on this filesystem")
        try:
            result = await forward_handler.handle(
                {
                    "method": "POST",
                    "path": "/api/raw",
                    "body_file_path": str(staged_path),
                }
            )
        finally:
            staged_path.unlink(missing_ok=True)

        assert result["status"] == 400
        assert "unexpected link count" in result["body"]["detail"]

    @pytest.mark.asyncio
    async def test_cancelling_staged_read_waits_for_inflight_file_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        read_started = threading.Event()
        release_read = threading.Event()

        def blocking_read(_descriptor: int, _size: int) -> bytes:
            read_started.set()
            assert release_read.wait(2)
            return b""

        monkeypatch.setattr(ipc_handlers.os, "read", blocking_read)
        read = asyncio.create_task(ipc_handlers._read_staged_request_body_chunk(17))
        assert await asyncio.to_thread(read_started.wait, 2)

        read.cancel()
        await asyncio.sleep(0.05)
        assert not read.done()

        release_read.set()
        with pytest.raises(asyncio.CancelledError):
            await read

    @pytest.mark.asyncio
    async def test_cancelling_staged_open_closes_late_descriptor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        open_started = threading.Event()
        release_open = threading.Event()
        read_descriptor, write_descriptor = os.pipe()

        def blocking_open(_path: Path) -> int:
            open_started.set()
            assert release_open.wait(2)
            return read_descriptor

        monkeypatch.setattr(
            ipc_handlers,
            "_open_staged_request_body",
            blocking_open,
        )
        opening = asyncio.create_task(
            ipc_handlers._open_staged_request_body_async(tmp_path / "staged")
        )
        try:
            assert await asyncio.to_thread(open_started.wait, 2)

            opening.cancel()
            await asyncio.sleep(0.05)
            assert not opening.done()

            release_open.set()
            with pytest.raises(asyncio.CancelledError):
                await opening
            with pytest.raises(OSError):
                os.fstat(read_descriptor)
        finally:
            release_open.set()
            for descriptor in (read_descriptor, write_descriptor):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    @pytest.mark.asyncio
    async def test_query_string(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle(
            {
                "method": "GET",
                "path": "/api/with-query",
                "query": "foo=bar",
            }
        )
        assert result["status"] == 200
        assert result["body"]["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_delete_with_path_param(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle(
            {
                "method": "DELETE",
                "path": "/api/items/abc123",
            }
        )
        assert result["status"] == 200
        assert result["body"]["deleted"] == "abc123"

    @pytest.mark.asyncio
    async def test_not_found(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle(
            {
                "method": "GET",
                "path": "/api/nonexistent",
            }
        )
        assert result["status"] == 404

    @pytest.mark.asyncio
    async def test_missing_params(self, forward_handler: ApiForwardHandler) -> None:
        result = await forward_handler.handle(None)
        assert result["status"] == 400

    @pytest.mark.asyncio
    async def test_binary_response_is_base64_encoded(
        self, forward_handler: ApiForwardHandler
    ) -> None:
        result = await forward_handler.handle(
            {
                "method": "GET",
                "path": "/api/file",
            }
        )
        assert result["status"] == 200
        assert result["headers"]["content-type"].startswith("image/png")
        assert result["body_encoding"] == "base64"
        assert result["body_base64"] == "iVBORw0K"
