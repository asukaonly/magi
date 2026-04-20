"""Remote plugin registry client.

Fetches plugin metadata from a JSON index hosted alongside plugin source
code in a single Git repository.  Individual plugins are installed by
downloading a tarball archive from GitHub and extracting only the needed
plugin subdirectory — no local git commands required.
"""
from __future__ import annotations

import io
import logging
import shutil
import tarfile
import tempfile
import time
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
TARBALL_TIMEOUT = 120  # seconds
INDEX_CACHE_TTL = 300  # 5 minutes


class PluginRegistryClient:
    """Client for the remote plugin registry backed by a Git repository."""

    def __init__(self, *, registry_url: str | None = None) -> None:
        config = get_config()
        configured_url = getattr(config.plugins, "registry_url", None)
        self._registry_url = registry_url or configured_url or DEFAULT_REGISTRY_URL
        self._cached_index: PluginRegistryIndex | None = None
        self._cache_timestamp: float = 0.0

    @property
    def _proxy_url(self) -> str | None:
        """Read proxy URL from live config each time so runtime changes apply."""
        return get_config().network.proxy_url()

    def _http_client(self, *, timeout: int = INDEX_TIMEOUT) -> httpx.AsyncClient:
        """Create an httpx client with the configured proxy (if any)."""
        kwargs: dict = {"timeout": timeout, "follow_redirects": True}
        if self._proxy_url:
            kwargs["proxy"] = self._proxy_url
        return httpx.AsyncClient(**kwargs)

    async def fetch_index(self, *, force: bool = False) -> PluginRegistryIndex:
        """Fetch the full plugin registry index, with TTL caching."""
        now = time.monotonic()
        if (
            not force
            and self._cached_index is not None
            and (now - self._cache_timestamp) < INDEX_CACHE_TTL
        ):
            return self._cached_index

        async with self._http_client() as client:
            response = await client.get(self._registry_url)
            response.raise_for_status()
            data = response.json()
        index = PluginRegistryIndex.model_validate(data)
        self._cached_index = index
        self._cache_timestamp = now
        return index

    async def fetch_entry(self, plugin_id: str) -> PluginRegistryEntry | None:
        """Fetch a single plugin entry from the registry."""
        index = self._cached_index or await self.fetch_index()
        for entry in index.plugins:
            if entry.plugin_id == plugin_id:
                return entry
        return None

    def _tarball_url(self, ref: str = "main") -> str:
        """Build the GitHub tarball URL from the repo URL."""
        repo_url = self._resolve_repo_url()
        # https://github.com/owner/repo.git → https://api.github.com/repos/owner/repo/tarball/main
        base = repo_url.removesuffix(".git").rstrip("/")
        if "github.com/" in base:
            parts = base.split("github.com/", 1)[1]
            return f"https://api.github.com/repos/{parts}/tarball/{ref}"
        # Non-GitHub: fall back to raw URL + archive convention.
        return f"{base}/archive/{ref}.tar.gz"

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
        """Download and extract a single plugin from the remote repository.

        Downloads the repo tarball from GitHub, streams it into a tar
        reader, and extracts only the plugin subdirectory.  No local git
        commands are required.

        Returns the path to the extracted plugin directory ready for
        installation by *PluginManager.install_plugin_from_directory()*.
        """
        if not entry.path:
            raise ValueError(f"No path defined for plugin: {entry.plugin_id}")

        tarball_url = self._tarball_url()

        dest = dest_dir or Path(tempfile.mkdtemp(prefix="magi-plugin-dl-"))
        dest.mkdir(parents=True, exist_ok=True)

        try:
            async with self._http_client(timeout=TARBALL_TIMEOUT) as client:
                resp = await client.get(tarball_url)
                resp.raise_for_status()
                tarball_bytes = resp.content

            plugin_dest = dest / entry.plugin_id
            _extract_subdir_from_tarball(tarball_bytes, entry.path, plugin_dest)

            logger.info(
                "Plugin source extracted",
                extra={"plugin_id": entry.plugin_id, "path": str(plugin_dest)},
            )
            return plugin_dest
        except Exception:
            # Clean up on failure.
            if dest_dir is None:
                shutil.rmtree(dest, ignore_errors=True)
            raise

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


def _extract_subdir_from_tarball(
    tarball_bytes: bytes,
    subdir: str,
    dest: Path,
) -> None:
    """Extract a subdirectory from a GitHub tarball archive.

    GitHub tarballs have a single top-level directory like
    ``owner-repo-sha/``.  This function locates the *subdir* within
    that prefix and extracts it to *dest*.
    """
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tf:
        # Discover the top-level prefix (e.g. "asukaonly-magi-plugins-abc1234/").
        members = tf.getmembers()
        if not members:
            raise ValueError("Empty tarball")

        top_prefix = members[0].name.split("/")[0] + "/"
        target_prefix = f"{top_prefix}{subdir}"
        # Normalise: strip trailing slash for consistent comparison.
        target_prefix = target_prefix.rstrip("/") + "/"

        extracted_any = False
        for member in members:
            if not member.name.startswith(target_prefix):
                continue

            # Security: prevent path traversal.
            rel_path = member.name[len(target_prefix):]
            if not rel_path:
                continue
            if ".." in rel_path.split("/"):
                continue

            target_path = dest / rel_path
            if member.isdir():
                target_path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src:  # type: ignore[union-attr]
                    if src is not None:
                        target_path.write_bytes(src.read())
            extracted_any = True

        if not extracted_any:
            raise ValueError(
                f"Plugin path '{subdir}' not found in tarball "
                f"(looked for '{target_prefix}' among {len(members)} entries)"
            )


def _version_newer(remote: str, local: str) -> bool:
    """Compare semver-style version strings (best-effort)."""
    try:
        remote_parts = [int(p) for p in remote.split(".")]
        local_parts = [int(p) for p in local.split(".")]
        return remote_parts > local_parts
    except (ValueError, AttributeError):
        return remote != local
