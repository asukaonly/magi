"""Plugin installation and uninstallation routes."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status

from ... import i18n as core_i18n
from ...plugins.install_service import DirectLibraryInstallError, PluginRegistryEntryNotFound
from ...plugins.icon_assets import resolve_plugin_icon
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
    PluginInstallJobSnapshot,
    PluginInstallRequest,
    PluginManifestResponse,
    PluginPackageResponse,
)

plugins_install_router = APIRouter()
logger = logging.getLogger(__name__)


@plugins_install_router.post("/install/upload", response_model=PluginPackageResponse)
async def install_plugin_from_upload(file: UploadFile):
    """Install a plugin from an uploaded .tar.gz or .zip archive."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t("plugins.errors.filename_required", fallback="Filename required"),
        )
    name = file.filename.lower()
    if not (name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".zip")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.archive_extension_invalid",
                fallback="Archive must be .tar.gz, .tgz, or .zip",
            ),
        )

    manager = _require_plugin_manager()
    install_service = _plugin_install_service(manager)
    with tempfile.TemporaryDirectory(prefix="magi-upload-") as tmp:
        archive_path = Path(tmp) / file.filename
        content = await file.read()
        archive_path.write_bytes(content)
        logger.info(
            "Plugin upload install requested",
            extra={
                "filename": file.filename,
                "archive_path": str(archive_path),
                "bytes": len(content),
            },
        )
        try:
            state = await install_service.install_from_archive(archive_path)
        except InvalidPluginArchiveError as exc:
            logger.warning(
                "Plugin upload install rejected (invalid archive)",
                extra={"filename": file.filename, "error": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=core_i18n.t(
                    "plugins.errors.archive_invalid",
                    fallback="The uploaded file is not a valid plugin archive",
                ),
            ) from exc
        except ValueError as exc:
            logger.warning(
                "Plugin upload install rejected",
                extra={"filename": file.filename, "error": str(exc)},
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception(
                "Plugin upload install failed",
                extra={"filename": file.filename, "error": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            ) from exc
    return _serialize_package(state)


@plugins_install_router.post("/install/upload/inspect", response_model=PluginManifestResponse)
async def inspect_plugin_upload(file: UploadFile):
    """Return declared capabilities + metadata of an uploaded archive WITHOUT
    installing it — drives the pre-install consent step for sideload."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t("plugins.errors.filename_required", fallback="Filename required"),
        )
    name = file.filename.lower()
    if not (name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".zip")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.archive_extension_invalid",
                fallback="Archive must be .tar.gz, .tgz, or .zip",
            ),
        )
    manager = _require_plugin_manager()
    with tempfile.TemporaryDirectory(prefix="magi-upload-inspect-") as tmp:
        archive_path = Path(tmp) / file.filename
        archive_path.write_bytes(await file.read())
        try:
            manifest = manager.inspect_plugin_archive(archive_path)
        except InvalidPluginArchiveError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=core_i18n.t(
                    "plugins.errors.archive_invalid",
                    fallback="The uploaded file is not a valid plugin archive",
                ),
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PluginManifestResponse(
        plugin_id=manifest.plugin_id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        icon=resolve_plugin_icon(manifest.icon, manifest.plugin_dir),
        display_group=manifest.display_group,
        official=False,  # sideload is never official
        contribution_types=[c.value for c in manifest.contribution_types],
        source="external",
        plugin_dir="",
        manifest_path="",
        capabilities=manifest.capabilities,
        consented_capabilities=None,
    )


@plugins_install_router.post("/install/upload/jobs", response_model=PluginInstallJobSnapshot)
async def start_plugin_upload_install_job(file: UploadFile):
    """Start a background plugin install job from an uploaded archive."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t("plugins.errors.filename_required", fallback="Filename required"),
        )
    name = file.filename.lower()
    if not (name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".zip")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.archive_extension_invalid",
                fallback="Archive must be .tar.gz, .tgz, or .zip",
            ),
        )

    tmp_path = Path(tempfile.mkdtemp(prefix="magi-upload-install-"))
    archive_path = tmp_path / file.filename
    content = await file.read()
    archive_path.write_bytes(content)
    logger.info(
        "Plugin upload install job requested",
        extra={"filename": file.filename, "archive_path": str(archive_path), "bytes": len(content)},
    )
    return plugin_install_jobs.start_upload_install(archive_path, file.filename)


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
    "inspect_plugin_upload",
    "install_plugin_from_registry",
    "install_plugin_from_upload",
    "get_plugin_install_job",
    "plugins_install_router",
    "start_plugin_registry_install_job",
    "start_plugin_upload_install_job",
    "uninstall_plugin",
]
