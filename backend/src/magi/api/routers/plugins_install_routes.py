"""Plugin installation and uninstallation routes."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status

from ... import i18n as core_i18n
from ...plugins.install_candidates import (
    PluginInstallCandidateClaimedError,
    PluginInstallCandidateDigestMismatchError,
    PluginInstallCandidateNotFoundError,
    get_plugin_install_candidate_store,
)
from ...plugins.install_service import DirectLibraryInstallError, PluginRegistryEntryNotFound
from ...plugins.package_files import InvalidPluginArchiveError
from .plugins_common import (
    _plugin_install_service,
    _require_plugin_manager,
    _serialize_package,
    _serialize_package_lightweight,
    _try_plugin_manager,
)
from .plugins_install_jobs import plugin_install_jobs, require_plugin_install_job
from .plugins_schemas import (
    PluginInstallCandidateApprovalRequest,
    PluginInstallCandidateResponse,
    PluginInstallJobSnapshot,
    PluginInstallRequest,
    PluginManifestResponse,
    PluginPackageResponse,
)

plugins_install_router = APIRouter()
logger = logging.getLogger(__name__)

MAX_PLUGIN_ARCHIVE_UPLOAD_BYTES = 8 * 1024 * 1024
PLUGIN_UPLOAD_CHUNK_BYTES = 64 * 1024


class _PluginArchiveUploadTooLargeError(ValueError):
    """Raised when an uploaded archive exceeds the route's compressed-size limit."""


def _archive_suffix(filename: str) -> str | None:
    name = filename.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return ".tar.gz"
    if name.endswith(".zip"):
        return ".zip"
    return None


def _display_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    return (normalized.rsplit("/", 1)[-1].strip() or "plugin-archive")[:255]


async def _write_candidate_archive(file: UploadFile, archive_path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total_bytes = 0
    with archive_path.open("xb") as handle:
        archive_path.chmod(0o600)
        while chunk := await file.read(PLUGIN_UPLOAD_CHUNK_BYTES):
            total_bytes += len(chunk)
            if total_bytes > MAX_PLUGIN_ARCHIVE_UPLOAD_BYTES:
                raise _PluginArchiveUploadTooLargeError
            digest.update(chunk)
            handle.write(chunk)
    if total_bytes == 0:
        raise InvalidPluginArchiveError("Plugin archive is empty")
    return digest.hexdigest(), total_bytes


def _candidate_manifest_response(manifest) -> PluginManifestResponse:
    return PluginManifestResponse(
        plugin_id=manifest.plugin_id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        icon=manifest.icon,
        display_group=manifest.display_group,
        official=False,
        contribution_types=[item.value for item in manifest.contribution_types],
        source="external",
        plugin_dir="",
        manifest_path="",
        capabilities=manifest.capabilities,
        consented_capabilities=None,
    )


@plugins_install_router.post(
    "/install/candidates",
    response_model=PluginInstallCandidateResponse,
)
async def create_plugin_install_candidate(file: UploadFile):
    """Stage and inspect one archive for later single-use installation approval."""

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t("plugins.errors.filename_required", fallback="Filename required"),
        )
    suffix = _archive_suffix(file.filename)
    if suffix is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.archive_extension_invalid",
                fallback="Archive must be .tar.gz, .tgz, or .zip",
            ),
        )

    store = get_plugin_install_candidate_store()
    candidate_id, archive_path = store.reserve_archive(suffix)
    filename = _display_filename(file.filename)
    try:
        archive_sha256, total_bytes = await _write_candidate_archive(file, archive_path)
        manager = _require_plugin_manager()
        manifest = await asyncio.to_thread(manager.inspect_plugin_archive, archive_path)
        if manifest.kind == "library":
            raise DirectLibraryInstallError(
                "Library components cannot be installed directly from an archive"
            )
        candidate = await asyncio.to_thread(
            store.register,
            candidate_id=candidate_id,
            archive_path=archive_path,
            original_filename=filename,
            archive_sha256=archive_sha256,
            manifest=manifest,
        )
    except _PluginArchiveUploadTooLargeError as exc:
        store.discard(candidate_id)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=core_i18n.t(
                "plugins.errors.archive_too_large",
                fallback="The plugin archive is too large",
            ),
        ) from exc
    except InvalidPluginArchiveError as exc:
        store.discard(candidate_id)
        logger.warning(
            "Plugin candidate rejected because the archive is invalid",
            extra={"upload_filename": filename, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.archive_invalid",
                fallback="The uploaded file is not a valid plugin archive",
            ),
        ) from exc
    except (DirectLibraryInstallError, ValueError) as exc:
        store.discard(candidate_id)
        logger.warning(
            "Plugin candidate rejected during manifest validation",
            extra={"upload_filename": filename, "error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except asyncio.CancelledError:
        store.discard(candidate_id)
        raise
    except Exception:
        store.discard(candidate_id)
        raise
    finally:
        await file.close()

    logger.info(
        "Plugin install candidate created",
        extra={
            "candidate_id": candidate.candidate_id,
            "upload_filename": filename,
            "archive_sha256": candidate.archive_sha256,
            "bytes": total_bytes,
        },
    )
    return PluginInstallCandidateResponse(
        candidate_id=candidate.candidate_id,
        archive_sha256=candidate.archive_sha256,
        expires_at_ms=int(candidate.expires_at * 1000),
        manifest=_candidate_manifest_response(candidate.manifest),
    )


@plugins_install_router.delete("/install/candidates/{candidate_id}")
async def discard_plugin_install_candidate(candidate_id: str):
    """Discard one unclaimed plugin install candidate."""

    store = get_plugin_install_candidate_store()
    try:
        store.get(candidate_id)
        store.discard(candidate_id)
    except PluginInstallCandidateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.install_candidate_not_found",
                fallback="Plugin install candidate not found or expired",
            ),
        ) from exc
    except PluginInstallCandidateClaimedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "plugins.errors.install_candidate_claimed",
                fallback="Plugin installation has already started",
            ),
        ) from exc
    return {"status": "ok", "candidate_id": candidate_id}


@plugins_install_router.post(
    "/install/candidates/{candidate_id}/jobs",
    response_model=PluginInstallJobSnapshot,
)
async def start_plugin_candidate_install_job(
    candidate_id: str,
    request: PluginInstallCandidateApprovalRequest,
):
    """Start one install job for the exact archive the user inspected."""

    try:
        return plugin_install_jobs.start_candidate_install(
            candidate_id,
            expected_sha256=request.expected_sha256,
        )
    except PluginInstallCandidateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.install_candidate_not_found",
                fallback="Plugin install candidate not found or expired",
            ),
        ) from exc
    except PluginInstallCandidateClaimedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "plugins.errors.install_candidate_claimed",
                fallback="Plugin installation has already started",
            ),
        ) from exc
    except PluginInstallCandidateDigestMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "plugins.errors.install_candidate_mismatch",
                fallback="The approved plugin package no longer matches the inspected package",
            ),
        ) from exc


@plugins_install_router.post("/install/registry", response_model=PluginPackageResponse)
async def install_plugin_from_registry(request: PluginInstallRequest):
    """Clone and install a plugin from the remote registry."""
    manager = _try_plugin_manager()
    install_service = _plugin_install_service(manager)

    try:
        logger.info(
            "Plugin registry install requested",
            extra={"plugin_id": request.plugin_id},
        )
        install_result = await install_service.install_from_registry(request.plugin_id)
        logger.info(
            "Plugin registry install completed",
            extra={
                "plugin_id": request.plugin_id,
                "auto_installed_deps": install_result.extra_installed,
            },
        )
        if install_result.used_runtime_manager:
            return _serialize_package(install_result.target_state)
        return _serialize_package_lightweight(install_result.target_state)
    except PluginRegistryEntryNotFound as exc:
        logger.warning("Plugin registry entry not found", extra={"plugin_id": request.plugin_id})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.not_found_in_registry", fallback="Plugin not found in registry"
            ),
        ) from exc
    except DirectLibraryInstallError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.library_not_directly_installable",
                fallback=str(exc),
            ),
        ) from exc
    except ValueError as exc:
        logger.warning(
            "Plugin registry install rejected",
            extra={"plugin_id": request.plugin_id, "error": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception(
            "Plugin registry install failed",
            extra={"plugin_id": request.plugin_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception(
            "Plugin registry install failed unexpectedly",
            extra={"plugin_id": request.plugin_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@plugins_install_router.post("/install/registry/jobs", response_model=PluginInstallJobSnapshot)
async def start_plugin_registry_install_job(request: PluginInstallRequest):
    """Start a background plugin install job from the remote registry."""
    return plugin_install_jobs.start_registry_install(request.plugin_id)


@plugins_install_router.get("/install/jobs/{job_id}", response_model=PluginInstallJobSnapshot)
async def get_plugin_install_job(job_id: str):
    """Return current status, progress, and logs for a plugin install job."""
    return require_plugin_install_job(job_id)


@plugins_install_router.delete("/{plugin_id}", status_code=status.HTTP_200_OK)
async def uninstall_plugin(plugin_id: str):
    """Uninstall a user-installed plugin."""
    manager = _require_plugin_manager()
    install_service = _plugin_install_service(manager)
    try:
        install_service.uninstall(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"status": "ok", "plugin_id": plugin_id}


__all__ = [
    "create_plugin_install_candidate",
    "discard_plugin_install_candidate",
    "install_plugin_from_registry",
    "get_plugin_install_job",
    "plugins_install_router",
    "start_plugin_candidate_install_job",
    "start_plugin_registry_install_job",
    "uninstall_plugin",
]
