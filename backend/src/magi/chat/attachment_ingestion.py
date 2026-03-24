"""Attachment ingestion service for desktop chat uploads."""

from __future__ import annotations

from pathlib import Path

from ..utils.runtime import RuntimePaths, get_runtime_paths
from .attachment_storage import LocalChatAttachmentStorage
from .pdf_attachment_parser import LocalPdfAttachmentParser
from .text_attachment_parser import LocalTextAttachmentParser

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


class LocalChatAttachmentIngestionService:
    """Normalize, store, and parse one uploaded desktop chat attachment."""

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
        """Store one attachment and return normalized payload metadata."""

        normalized_name = Path(str(original_name or "").strip()).name
        normalized_mime_type = str(mime_type or "application/octet-stream").strip().lower()
        attachment_kind = self._classify_attachment_kind(
            original_name=normalized_name,
            mime_type=normalized_mime_type,
        )
        if attachment_kind is None:
            raise ValueError("Unsupported attachment type.")
        if not content:
            raise ValueError("Empty file is not allowed.")

        if attachment_kind == "image":
            stored = self._storage.store_image_attachment(
                session_id=session_id,
                turn_id=turn_id,
                original_name=normalized_name,
                content=content,
                mime_type=normalized_mime_type,
            )
            return {
                "attachment_id": stored.attachment_id,
                "kind": "image",
                "original_name": stored.original_name,
                "mime_type": stored.mime_type,
                "size_bytes": stored.size_bytes,
                "storage_path": stored.storage_path,
                "sha256": stored.sha256,
                "parse_status": "not_applicable",
            }

        stored = self._storage.store_file_attachment(
            session_id=session_id,
            turn_id=turn_id,
            original_name=normalized_name,
            content=content,
            mime_type=normalized_mime_type,
        )

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

    def _build_text_payload(
        self,
        *,
        session_id: str,
        turn_id: str,
        stored,
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
        stored,
    ) -> dict[str, object]:
        parsed = self._pdf_parser.parse_file(stored.storage_path)
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
        if parsed.extraction_succeeded:
            payload["derived_text_path"] = self._write_derived_text(
                session_id=session_id,
                turn_id=turn_id,
                attachment_id=stored.attachment_id,
                text=parsed.text,
            )
        if parsed.error:
            payload["parse_error"] = parsed.error
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
