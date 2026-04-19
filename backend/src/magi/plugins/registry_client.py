"""Remote plugin registry client.

Fetches plugin metadata from a JSON index hosted alongside plugin source
code in a single Git repository.  Individual plugins are installed by
cloning the repository (shallow, depth-1) and copying the relevant
subdirectory rather than downloading separate release archives.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from ..config import get_config
from .contracts import PluginRegistryEntry, PluginRegistryIndex

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/asukaonly/magi-plugins/main/registry.json"
)
DEFAULT_REPO_URL = "https://github.com/asukaonly/magi-plugins.git"
INDEX_TIMEOUT = 30
GIT_CLONE_TIMEOUT = 120  # seconds


class PluginRegistryClient:
    """Client for the remote plugin registry backed by a Git repository."""

    def __init__(self, *, registry_url: str | None = None) -> None:
        config = get_config()
        configured_url = getattr(config.plugins, "registry_url", None)
        self._registry_url = registry_url or configured_url or DEFAULT_REGISTRY_URL
        self._cached_index: PluginRegistryIndex | None = None

    async def fetch_index(self) -> PluginRegistryIndex:
        """Fetch the full plugin registry index."""
        async with httpx.AsyncClient(timeout=INDEX_TIMEOUT) as client:
            response = await client.get(self._registry_url)
            response.raise_for_status()
            data = response.json()
        index = PluginRegistryIndex.model_validate(data)
        self._cached_index = index
        return index

    async def fetch_entry(self, plugin_id: str) -> PluginRegistryEntry | None:
        """Fetch a single plugin entry from the registry."""
        index = self._cached_index or await self.fetch_index()
        for entry in index.plugins:
            if entry.plugin_id == plugin_id:
                return entry
        return None

    def _resolve_repo_url(self) -> str:
        """Return the Git repo URL from the cached index or the default."""
        if self._cached_index and self._cached_index.repo_url:
            return self._cached_index.repo_url
        return DEFAULT_REPO_URL

    async def clone_plugin(
        self,
        entry: PluginRegistryEntry,
        *,
        dest_dir: Path | None = None,
    ) -> Path:
        """Clone the plugin repo and extract the plugin subdirectory.

        Returns the path to the extracted plugin directory ready for
        installation by *PluginManager.install_plugin_from_directory()*.
        """
        if not entry.path:
            raise ValueError(f"No path defined for plugin: {entry.plugin_id}")

        repo_url = self._resolve_repo_url()
        dest = dest_dir or Path(tempfile.mkdtemp(prefix="magi-plugin-clone-"))
        dest.mkdir(parents=True, exist_ok=True)

        clone_dir = dest / "_repo"

        # Shallow clone — fast, minimal bandwidth.
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            "--sparse",
            repo_url,
            str(clone_dir),
        ]
        logger.info(
            "Cloning plugin repository",
            extra={"repo": repo_url, "plugin_id": entry.plugin_id},
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=GIT_CLONE_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git clone failed (exit {result.returncode}): {result.stderr.strip()}"
            )

        # Sparse checkout: only materialise the plugin we need.
        sparse_cmd = [
            "git",
            "-C",
            str(clone_dir),
            "sparse-checkout",
            "set",
            entry.path,
        ]
        result = subprocess.run(
            sparse_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git sparse-checkout failed: {result.stderr.strip()}"
            )

        plugin_src = clone_dir / entry.path
        if not plugin_src.is_dir():
            raise ValueError(
                f"Plugin path '{entry.path}' not found in cloned repository"
            )

        # Copy the plugin directory out of the sparse clone.
        plugin_dest = dest / entry.plugin_id
        shutil.copytree(plugin_src, plugin_dest)

        # Clean up the clone.
        shutil.rmtree(clone_dir, ignore_errors=True)

        logger.info(
            "Plugin source extracted",
            extra={"plugin_id": entry.plugin_id, "path": str(plugin_dest)},
        )
        return plugin_dest

    async def check_updates(
        self,
        installed: dict[str, str],
    ) -> list[PluginRegistryEntry]:
        """Return registry entries for plugins that have a newer version.

        *installed* maps ``plugin_id`` → currently installed ``version``.
        """
        index = await self.fetch_index()
        updates: list[PluginRegistryEntry] = []
        for entry in index.plugins:
            local_version = installed.get(entry.plugin_id)
            if local_version is None:
                continue
            if _version_newer(entry.version, local_version):
                updates.append(entry)
        return updates


def _version_newer(remote: str, local: str) -> bool:
    """Compare semver-style version strings (best-effort)."""
    try:
        remote_parts = [int(p) for p in remote.split(".")]
        local_parts = [int(p) for p in local.split(".")]
        return remote_parts > local_parts
    except (ValueError, AttributeError):
        return remote != local
