"""Attachment ingestion service for desktop chat uploads."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from magi_plugin_sdk.image_generation import (
    MAX_IMAGE_ATTACHMENT_BYTES,
)  # promoted to SDK; re-exported here for host use

from ..core.logger import get_logger
from ..i18n import t
from ..utils.runtime import RuntimePaths, get_runtime_paths
from ..core.chat_assets.io import (
    open_managed_chat_attachment,
    write_managed_chat_asset_atomically,
)
from ..core.chat_assets.paths import (
    normalize_chat_asset_component,
    prepare_chat_derived_write_path,
    resolve_chat_attachment_file,
    resolve_chat_derived_file,
)
from ..core.chat_assets.mutations import (
    chat_asset_mutation,
    run_chat_asset_mutation_held,
)
from .attachment_storage import LocalChatAttachmentStorage, StoredChatAttachment
from .image_preview_conversion import HeicPreviewConverter, PillowHeicPreviewConverter
from .pdf_attachment_parser import (
    PDF_PARSER_BACKEND,
    PDF_PARSER_BACKEND_VERSION,
    LocalPdfAttachmentParser,
)
from .text_attachment_parser import LocalTextAttachmentParser
from .session_mutations import chat_session_mutation

logger = get_logger(__name__)

SUPPORTED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}
SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
CONVERTIBLE_HEIC_MIME_TYPES = {
    "image/heic",
    "image/heif",
}
CONVERTIBLE_HEIC_EXTENSIONS = {
    ".heic",
    ".heif",
}
PREVIEW_IMAGE_MIME_TYPE = "image/jpeg"
SUPPORTED_PDF_MIME_TYPES = {"application/pdf"}
SUPPORTED_TEXT_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/sql",
    "application/toml",
    "application/x-httpd-php",
    "application/x-sh",
    "application/xml",
    "application/yaml",
    "text/csv",
    "text/html",
    "text/javascript",
    "text/jsx",
    "text/markdown",
    "text/plain",
    "text/tsx",
    "text/typescript",
    "text/x-c",
    "text/x-c++",
    "text/x-go",
    "text/x-java-source",
    "text/x-python",
    "text/x-ruby",
    "text/x-rust",
    "text/x-shellscript",
    "text/xml",
}
SUPPORTED_TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".csv",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".kt",
    ".log",
    ".md",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
MAX_FILE_ATTACHMENT_BYTES = 50 * 1024 * 1024


class ChatSessionReadPort(Protocol):
    """Read the owning chat session before publishing an attachment."""

    async def aget_session_summary(
        self,
        user_id: str,
        session_id: str,
    ) -> object | None:
        """Return the owned session, or ``None`` when it is unavailable."""


class LocalChatAttachmentIngestionService:
    """Normalize, store, and prepare chat attachments for runtime use."""

    def __init__(
        self,
        *,
        runtime_paths: RuntimePaths | None = None,
        storage: LocalChatAttachmentStorage | None = None,
        text_parser: LocalTextAttachmentParser | None = None,
        pdf_parser: LocalPdfAttachmentParser | None = None,
        heic_preview_converter: HeicPreviewConverter | None = None,
        chat_read_service_factory: Callable[[], ChatSessionReadPort] | None = None,
    ) -> None:
        self._runtime_paths = runtime_paths or get_runtime_paths()
        self._storage = storage or LocalChatAttachmentStorage(runtime_paths=self._runtime_paths)
        self._text_parser = text_parser or LocalTextAttachmentParser()
        self._pdf_parser = pdf_parser or LocalPdfAttachmentParser()
        self._heic_preview_converter = heic_preview_converter or PillowHeicPreviewConverter()
        self._chat_read_service_factory = chat_read_service_factory

    async def ingest_uploaded_attachment(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, object] | None:
        """Validate ownership and persist one upload under the chat boundary."""

        normalized_session_id = normalize_chat_asset_component(
            session_id,
            label="session_id",
        )
        normalized_turn_id = normalize_chat_asset_component(
            turn_id,
            label="turn_id",
        )
        async with chat_session_mutation(normalized_session_id):
            async with chat_asset_mutation():
                read_service = self._resolve_chat_read_service()
                session = await read_service.aget_session_summary(
                    user_id,
                    normalized_session_id,
                )
                if session is None:
                    return None
                return await run_chat_asset_mutation_held(
                    self.ingest_attachment,
                    session_id=normalized_session_id,
                    turn_id=normalized_turn_id,
                    original_name=original_name,
                    content=content,
                    mime_type=mime_type,
                )

    def _resolve_chat_read_service(self) -> ChatSessionReadPort:
        if self._chat_read_service_factory is not None:
            return self._chat_read_service_factory()
        from .read_service import get_chat_read_service

        return get_chat_read_service()

    def ingest_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, object]:
        """Store one attachment and return normalized upload metadata."""

        normalized_name = Path(str(original_name or "").strip()).name
        normalized_mime_type = str(mime_type or "application/octet-stream").strip().lower()
        conversion_payload: dict[str, object] = {}
        if self._is_convertible_heic(original_name=normalized_name, mime_type=normalized_mime_type):
            if not content:
                raise ValueError(
                    t("chat.attachments.empty_file", fallback="Empty file is not allowed.")
                )
            source_original_name = normalized_name
            source_original_mime_type = normalized_mime_type
            try:
                content = self._heic_preview_converter.convert_heic_to_jpeg(
                    content=bytes(content),
                    original_name=source_original_name,
                )
            except Exception as exc:
                raise ValueError(f"HEIC image conversion failed: {exc}") from exc
            normalized_name = self._jpeg_preview_name(source_original_name)
            normalized_mime_type = PREVIEW_IMAGE_MIME_TYPE
            conversion_payload = {
                "source_original_name": source_original_name,
                "source_original_mime_type": source_original_mime_type,
                "preview_generated": True,
                "preview_mime_type": PREVIEW_IMAGE_MIME_TYPE,
            }
        attachment_kind = self._classify_attachment_kind(
            original_name=normalized_name,
            mime_type=normalized_mime_type,
        )
        if attachment_kind is None:
            raise ValueError(
                t("chat.attachments.unsupported_type", fallback="Unsupported attachment type.")
            )
        if not content:
            raise ValueError(
                t("chat.attachments.empty_file", fallback="Empty file is not allowed.")
            )
        if attachment_kind == "image" and len(content) > MAX_IMAGE_ATTACHMENT_BYTES:
            raise ValueError(
                t(
                    "chat.attachments.image_too_large",
                    fallback="Image attachment exceeds the 20 MB limit.",
                )
            )
        if attachment_kind != "image" and len(content) > MAX_FILE_ATTACHMENT_BYTES:
            raise ValueError(
                t(
                    "chat.attachments.file_too_large",
                    fallback="File attachment exceeds the 50 MB limit.",
                )
            )

        if attachment_kind == "image":
            stored = self._storage.store_image_attachment(
                session_id=session_id,
                turn_id=turn_id,
                original_name=normalized_name,
                content=content,
                mime_type=normalized_mime_type,
            )
            payload = self._build_uploaded_payload(stored=stored, attachment_kind=attachment_kind)
            payload["session_id"] = normalize_chat_asset_component(
                session_id,
                label="session_id",
            )
            payload["turn_id"] = normalize_chat_asset_component(
                turn_id,
                label="turn_id",
            )
            payload.update(conversion_payload)
            return payload

        stored = self._storage.store_file_attachment(
            session_id=session_id,
            turn_id=turn_id,
            original_name=normalized_name,
            content=content,
            mime_type=normalized_mime_type,
        )

        payload = self._build_uploaded_payload(stored=stored, attachment_kind=attachment_kind)
        payload["session_id"] = normalize_chat_asset_component(
            session_id,
            label="session_id",
        )
        payload["turn_id"] = normalize_chat_asset_component(
            turn_id,
            label="turn_id",
        )
        payload.update(conversion_payload)
        return payload

    def ingest_local_file(
        self,
        *,
        session_id: str,
        turn_id: str,
        file_path: str,
        original_name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, object]:
        """Import one existing local file into managed chat attachment storage."""

        source_path = Path(str(file_path or "").strip())
        if not source_path.is_file():
            raise ValueError("Attachment source file not found.")
        resolved_name = Path(str(original_name or "").strip()).name or source_path.name
        resolved_mime_type = str(
            mime_type or mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        )
        payload = self.ingest_attachment(
            session_id=session_id,
            turn_id=turn_id,
            original_name=resolved_name,
            content=source_path.read_bytes(),
            mime_type=resolved_mime_type,
        )
        payload["source_path"] = str(source_path)
        payload["source_origin"] = "local_file"
        return payload

    def prepare_runtime_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        attachment: dict[str, object],
    ) -> dict[str, object]:
        """Parse one already-managed attachment for prompt/runtime consumption."""

        payload = dict(attachment)
        try:
            normalized_session_id = normalize_chat_asset_component(
                session_id,
                label="session_id",
            )
            normalized_turn_id = normalize_chat_asset_component(
                turn_id,
                label="turn_id",
            )
            normalized_attachment_id = normalize_chat_asset_component(
                payload.get("attachment_id"),
                label="attachment_id",
            )
        except ValueError as exc:
            payload.pop("storage_path", None)
            payload.pop("derived_text_path", None)
            return self._mark_parse_failed(payload, str(exc))
        payload["session_id"] = normalized_session_id
        payload["turn_id"] = normalized_turn_id
        payload["attachment_id"] = normalized_attachment_id
        attachment_kind = self._resolve_payload_kind(payload)
        if attachment_kind is None:
            return payload
        payload["kind"] = attachment_kind
        resolved_storage_path = resolve_chat_attachment_file(
            payload.get("storage_path"),
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=normalized_attachment_id,
            runtime_paths=self._runtime_paths,
        )
        if resolved_storage_path is None:
            payload.pop("storage_path", None)
        else:
            payload["storage_path"] = str(resolved_storage_path)
        if attachment_kind == "image":
            if resolved_storage_path is None:
                return self._mark_parse_failed(
                    payload,
                    "Attachment file not found in the managed chat turn.",
                )
            return payload
        raw_derived_path = str(payload.get("derived_text_path") or "").strip()
        if raw_derived_path:
            resolved_derived_path = resolve_chat_derived_file(
                raw_derived_path,
                session_id=normalized_session_id,
                turn_id=normalized_turn_id,
                attachment_id=normalized_attachment_id,
                runtime_paths=self._runtime_paths,
            )
            if resolved_derived_path is None:
                payload.pop("derived_text_path", None)
                if not str(payload.get("derived_text_excerpt") or "").strip():
                    payload["parse_status"] = "pending"
            else:
                payload["derived_text_path"] = str(resolved_derived_path)
        if self._is_prepared_payload(payload):
            return payload

        stored = self._stored_from_payload(
            payload,
            attachment_kind=attachment_kind,
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
        )
        if stored is None:
            return self._mark_parse_failed(payload, "Attachment file not found.")

        try:
            if attachment_kind == "pdf":
                return self._build_pdf_payload(
                    session_id=session_id,
                    turn_id=turn_id,
                    stored=stored,
                )
            return self._build_text_payload(
                session_id=session_id,
                turn_id=turn_id,
                stored=stored,
            )
        except Exception as exc:
            logger.warning(
                "Chat attachment runtime preparation failed",
                session_id=session_id,
                turn_id=turn_id,
                attachment_id=str(payload.get("attachment_id") or ""),
                kind=attachment_kind,
                error=str(exc),
                exc_info=True,
            )
            return self._mark_parse_failed(payload, str(exc) or "Attachment parsing failed.")

    @staticmethod
    def _build_uploaded_payload(
        *,
        stored: StoredChatAttachment,
        attachment_kind: str,
    ) -> dict[str, object]:
        return {
            "attachment_id": stored.attachment_id,
            "kind": attachment_kind,
            "original_name": stored.original_name,
            "mime_type": stored.mime_type,
            "size_bytes": stored.size_bytes,
            "storage_path": stored.storage_path,
            "sha256": stored.sha256,
            "parse_status": "not_applicable" if attachment_kind == "image" else "pending",
        }

    def _build_text_payload(
        self,
        *,
        session_id: str,
        turn_id: str,
        stored: StoredChatAttachment,
    ) -> dict[str, object]:
        handle = open_managed_chat_attachment(
            stored.storage_path,
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=stored.attachment_id,
            original_name=stored.original_name,
            runtime_paths=self._runtime_paths,
        )
        if handle is None:
            raise ValueError("Attachment file not found.")
        with handle:
            parsed = self._text_parser.parse_bytes(handle.read())
        derived_text_path = self._write_derived_text(
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=stored.attachment_id,
            text=parsed.text,
        )
        return {
            "attachment_id": stored.attachment_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "kind": "text_file",
            "original_name": stored.original_name,
            "mime_type": stored.mime_type,
            "size_bytes": stored.size_bytes,
            "storage_path": stored.storage_path,
            "sha256": stored.sha256,
            "parse_status": "parsed",
            "derived_text_path": derived_text_path,
            "derived_text_excerpt": parsed.excerpt,
            "character_count": parsed.character_count,
            "truncated": parsed.truncated,
            "encoding": parsed.encoding,
        }

    def _build_pdf_payload(
        self,
        *,
        session_id: str,
        turn_id: str,
        stored: StoredChatAttachment,
    ) -> dict[str, object]:
        logger.info(
            "Starting PDF attachment text extraction",
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=stored.attachment_id,
            original_name=stored.original_name,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            storage_path=stored.storage_path,
            sha256_prefix=str(stored.sha256)[:12],
            parser_backend=PDF_PARSER_BACKEND,
            parser_version=PDF_PARSER_BACKEND_VERSION,
        )
        handle = open_managed_chat_attachment(
            stored.storage_path,
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=stored.attachment_id,
            original_name=stored.original_name,
            runtime_paths=self._runtime_paths,
        )
        if handle is None:
            raise ValueError("Attachment file not found.")
        with handle:
            parsed = self._pdf_parser.parse_stream(handle)
        derived_text_path: str | None = None
        if parsed.extraction_succeeded:
            derived_text_path = self._write_derived_text(
                session_id=session_id,
                turn_id=turn_id,
                attachment_id=stored.attachment_id,
                text=parsed.text,
            )
        payload: dict[str, object] = {
            "attachment_id": stored.attachment_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "kind": "pdf",
            "original_name": stored.original_name,
            "mime_type": stored.mime_type,
            "size_bytes": stored.size_bytes,
            "storage_path": stored.storage_path,
            "sha256": stored.sha256,
            "parse_status": "parsed" if parsed.extraction_succeeded else "failed",
            "derived_text_excerpt": parsed.excerpt,
            "character_count": parsed.character_count,
            "truncated": parsed.truncated,
            "page_count": parsed.page_count,
            "extraction_succeeded": parsed.extraction_succeeded,
        }
        if derived_text_path is not None:
            payload["derived_text_path"] = derived_text_path
        if parsed.error:
            payload["parse_error"] = parsed.error
        log_payload = {
            "session_id": session_id,
            "turn_id": turn_id,
            "attachment_id": stored.attachment_id,
            "original_name": stored.original_name,
            "size_bytes": stored.size_bytes,
            "storage_path": stored.storage_path,
            "parser_backend": PDF_PARSER_BACKEND,
            "parser_version": PDF_PARSER_BACKEND_VERSION,
            "parse_status": payload["parse_status"],
            "page_count": parsed.page_count,
            "character_count": parsed.character_count,
            "truncated": parsed.truncated,
            "derived_text_path": derived_text_path,
            "parse_error": parsed.error,
        }
        if parsed.extraction_succeeded:
            logger.info("PDF attachment text extraction completed", **log_payload)
        else:
            logger.warning("PDF attachment text extraction failed", **log_payload)
        return payload

    def _stored_from_payload(
        self,
        payload: dict[str, object],
        *,
        attachment_kind: str,
        session_id: str,
        turn_id: str,
    ) -> StoredChatAttachment | None:
        attachment_id = str(payload.get("attachment_id") or "").strip()
        try:
            attachment_id = normalize_chat_asset_component(
                attachment_id,
                label="attachment_id",
            )
        except ValueError:
            return None
        storage_path = resolve_chat_attachment_file(
            payload.get("storage_path"),
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=attachment_id,
            runtime_paths=self._runtime_paths,
        )
        if storage_path is None:
            return None
        size_bytes = payload.get("size_bytes")
        try:
            normalized_size = int(str(size_bytes or storage_path.stat().st_size))
        except (OSError, TypeError, ValueError):
            normalized_size = 0
        return StoredChatAttachment(
            attachment_id=attachment_id,
            kind=attachment_kind,
            original_name=str(payload.get("original_name") or storage_path.name).strip()
            or storage_path.name,
            mime_type=str(payload.get("mime_type") or "application/octet-stream").strip()
            or "application/octet-stream",
            size_bytes=normalized_size,
            storage_path=str(storage_path),
            sha256=str(payload.get("sha256") or "").strip(),
        )

    def _resolve_payload_kind(self, payload: dict[str, object]) -> str | None:
        explicit_kind = str(payload.get("kind") or "").strip()
        if explicit_kind in {"image", "pdf", "text_file"}:
            return explicit_kind
        if explicit_kind == "mcp_resource":
            return None
        return self._classify_attachment_kind(
            original_name=str(payload.get("original_name") or "").strip(),
            mime_type=str(payload.get("mime_type") or "application/octet-stream").strip().lower(),
        )

    @staticmethod
    def _is_prepared_payload(payload: dict[str, object]) -> bool:
        parse_status = str(payload.get("parse_status") or "").strip()
        if parse_status != "parsed":
            return False
        return bool(str(payload.get("derived_text_path") or "").strip()) or bool(
            str(payload.get("derived_text_excerpt") or "").strip()
        )

    @staticmethod
    def _mark_parse_failed(payload: dict[str, object], error: str) -> dict[str, object]:
        payload["parse_status"] = "failed"
        payload["parse_error"] = error
        payload.setdefault("derived_text_excerpt", "")
        payload.setdefault("character_count", 0)
        payload.setdefault("truncated", False)
        return payload

    def _write_derived_text(
        self,
        *,
        session_id: str,
        turn_id: str,
        attachment_id: str,
        text: str,
    ) -> str:
        target_path = prepare_chat_derived_write_path(
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=attachment_id,
            runtime_paths=self._runtime_paths,
        )
        write_managed_chat_asset_atomically(
            target_path,
            str(text).encode("utf-8"),
        )
        return str(target_path)

    @staticmethod
    def _classify_attachment_kind(*, original_name: str, mime_type: str) -> str | None:
        extension = Path(original_name).suffix.lower()
        if mime_type in SUPPORTED_IMAGE_MIME_TYPES or extension in SUPPORTED_IMAGE_EXTENSIONS:
            return "image"
        if mime_type in SUPPORTED_PDF_MIME_TYPES or extension == ".pdf":
            return "pdf"
        if (
            mime_type.startswith("text/")
            or mime_type in SUPPORTED_TEXT_MIME_TYPES
            or extension in SUPPORTED_TEXT_EXTENSIONS
        ):
            return "text_file"
        return None

    @staticmethod
    def _is_convertible_heic(*, original_name: str, mime_type: str) -> bool:
        extension = Path(original_name).suffix.lower()
        return mime_type in CONVERTIBLE_HEIC_MIME_TYPES or extension in CONVERTIBLE_HEIC_EXTENSIONS

    @staticmethod
    def _jpeg_preview_name(original_name: str) -> str:
        path = Path(str(original_name or "").strip()).name
        stem = Path(path).stem if path else "attachment"
        return f"{stem or 'attachment'}.jpg"
