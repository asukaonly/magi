"""Plugin installation and uninstallation routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status

from .plugins_common import legacy_plugins_module
from .plugins_schemas import PluginInstallRequest, PluginPackageResponse

plugins_install_router = APIRouter()


@plugins_install_router.post("/install/upload", response_model=PluginPackageResponse)
async def install_plugin_from_upload(file: UploadFile):
    """Install a plugin from an uploaded .tar.gz or .zip archive."""
    legacy = legacy_plugins_module()
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename required")
    name = file.filename.lower()
    if not (name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".zip")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archive must be .tar.gz, .tgz, or .zip")

    manager = legacy.resolve_plugin_manager()
    with tempfile.TemporaryDirectory(prefix="magi-upload-") as tmp:
        archive_path = Path(tmp) / file.filename
        content = await file.read()
        archive_path.write_bytes(content)
        try:
            state = manager.install_plugin_from_archive(archive_path)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return legacy._serialize_package(state)


@plugins_install_router.post("/install/registry", response_model=PluginPackageResponse)
async def install_plugin_from_registry(request: PluginInstallRequest):
    """Clone and install a plugin from the remote registry."""
    legacy = legacy_plugins_module()
    manager = legacy._try_plugin_manager()
    registry = legacy._get_registry_client()

    entry = await registry.fetch_entry(request.plugin_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found in registry")

    try:
        plugin_dir = await registry.clone_plugin(entry)
        if manager is not None:
            state = manager.install_plugin_from_directory(plugin_dir)
            return legacy._serialize_package(state)

        state = legacy._lightweight_install(plugin_dir, entry)
        return legacy._serialize_package_lightweight(state)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@plugins_install_router.delete("/{plugin_id}", status_code=status.HTTP_200_OK)
async def uninstall_plugin(plugin_id: str):
    """Uninstall a user-installed plugin."""
    legacy = legacy_plugins_module()
    manager = legacy.resolve_plugin_manager()
    try:
        manager.uninstall_plugin(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"status": "ok", "plugin_id": plugin_id}


__all__ = [
    "install_plugin_from_registry",
    "install_plugin_from_upload",
    "plugins_install_router",
    "uninstall_plugin",
]