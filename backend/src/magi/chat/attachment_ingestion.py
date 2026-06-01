"""Attachment ingestion service for desktop chat uploads."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from magi_plugin_sdk.image_generation import MAX_IMAGE_ATTACHMENT_BYTES  # promoted to SDK; re-exported here for host use

from ..core.logger import get_logger
from ..i18n import t
from ..utils.runtime import RuntimePaths, get_runtime_paths
from .attachment_storage import LocalChatAttachmentStorage, StoredChatAttachment
from .pdf_attachment_parser import PDF_PARSER_BACKEND, PDF_PARSER_BACKEND_VERSION, LocalPdfAttachmentParser
from .text_attachment_parser import LocalTextAttachmentParser

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


class LocalChatAttachmentIngestionService:
    """Normalize, store, and prepare chat attachments for runtime use."""

    def __init__(
        self,
        *,
        runtime_paths: RuntimePaths | None = None,
        storage: LocalChatAttachmentStorage | None = None,
        text_parser: LocalTextAttachmentParser | None = None,
        pdf_parser: LocalPdfAttachmentParser | None = None,
    ) -> None:
        self._runtime_paths = runtime_paths or get_runtime_paths()
        self._storage = storage or LocalChatAttachmentStorage(runtime_paths=self._runtime_paths)
        self._text_parser = text_parser or LocalTextAttachmentParser()
        self._pdf_parser = pdf_parser or LocalPdfAttachmentParser()

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
        attachment_kind = self._classify_attachment_kind(
            original_name=normalized_name,
            mime_type=normalized_mime_type,
        )
        if attachment_kind is None:
            raise ValueError(t("chat.attachments.unsupported_type", fallback="Unsupported attachment type."))
        if not content:
            raise ValueError(t("chat.attachments.empty_file", fallback="Empty file is not allowed."))
        if attachment_kind == "image" and len(content) > MAX_IMAGE_ATTACHMENT_BYTES:
            raise ValueError(t("chat.attachments.image_too_large", fallback="Image attachment exceeds the 20 MB limit."))
        if attachment_kind != "image" and len(content) > MAX_FILE_ATTACHMENT_BYTES:
            raise ValueError(t("chat.attachments.file_too_large", fallback="File attachment exceeds the 50 MB limit."))

        if attachment_kind == "image":
            stored = self._storage.store_image_attachment(
                session_id=session_id,
                turn_id=turn_id,
                original_name=normalized_name,
                content=content,
                mime_type=normalized_mime_type,
            )
            return self._build_uploaded_payload(stored=stored, attachment_kind=attachment_kind)

        stored = self._storage.store_file_attachment(
            session_id=session_id,
            turn_id=turn_id,
            original_name=normalized_name,
            content=content,
            mime_type=normalized_mime_type,
        )

        return self._build_uploaded_payload(stored=stored, attachment_kind=attachment_kind)

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
        attachment_kind = self._resolve_payload_kind(payload)
        if attachment_kind is None:
            return payload
        payload["kind"] = attachment_kind
        if attachment_kind == "image":
            return payload
        if self._is_prepared_payload(payload):
            return payload

        stored = self._stored_from_payload(payload, attachment_kind=attachment_kind)
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
        parsed = self._text_parser.parse_file(stored.storage_path)
        derived_text_path = self._write_derived_text(
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=stored.attachment_id,
            text=parsed.text,
        )
        return {
            "attachment_id": stored.attachment_id,
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
        parsed = self._pdf_parser.parse_file(stored.storage_path)
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
    ) -> StoredChatAttachment | None:
        storage_path = self._resolve_managed_storage_path(
            str(payload.get("storage_path") or "").strip()
        )
        if storage_path is None:
            return None
        attachment_id = str(payload.get("attachment_id") or "").strip()
        if not attachment_id:
            return None
        size_bytes = payload.get("size_bytes")
        try:
            normalized_size = int(str(size_bytes or storage_path.stat().st_size))
        except (OSError, TypeError, ValueError):
            normalized_size = 0
        return StoredChatAttachment(
            attachment_id=attachment_id,
            kind=attachment_kind,
            original_name=str(payload.get("original_name") or storage_path.name).strip() or storage_path.name,
            mime_type=str(payload.get("mime_type") or "application/octet-stream").strip()
            or "application/octet-stream",
            size_bytes=normalized_size,
            storage_path=str(storage_path),
            sha256=str(payload.get("sha256") or "").strip(),
        )

    def _resolve_managed_storage_path(self, storage_path: str) -> Path | None:
        if not storage_path:
            return None
        candidate = Path(storage_path)
        try:
            resolved = candidate.resolve()
            resolved.relative_to(self._runtime_paths.base_dir.resolve())
        except Exception:
            return None
        return resolved if resolved.is_file() else None

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
        target_dir = self._runtime_paths.chat_derived_dir / session_id / turn_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{attachment_id}.txt"
        target_path.write_text(text, encoding="utf-8")
        return str(target_path)

    @staticmethod
    def _classify_attachment_kind(*, original_name: str, mime_type: str) -> str | None:
        extension = Path(original_name).suffix.lower()
        if mime_type in SUPPORTED_IMAGE_MIME_TYPES or extension in SUPPORTED_IMAGE_EXTENSIONS:
            return "image"
        if mime_type in SUPPORTED_PDF_MIME_TYPES or extension == ".pdf":
            return "pdf"
        if mime_type.startswith("text/") or mime_type in SUPPORTED_TEXT_MIME_TYPES or extension in SUPPORTED_TEXT_EXTENSIONS:
            return "text_file"
        return None
