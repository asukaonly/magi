"""Remote plugin registry client.

Fetches plugin metadata from a JSON index hosted alongside plugin source
code in a single Git repository.  Individual plugins are installed via a
shared local bare clone of the repository; only the requested plugin
subdirectory is materialised through sparse checkout.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
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
GIT_CLONE_TIMEOUT = 120  # seconds
INDEX_CACHE_TTL = 300  # 5 minutes
REPO_CACHE_DIR = Path("~/.magi/cache/plugin-repo").expanduser()


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

    def _http_client(self) -> httpx.AsyncClient:
        """Create an httpx client with the configured proxy (if any)."""
        kwargs: dict = {"timeout": INDEX_TIMEOUT}
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

    def _resolve_repo_url(self) -> str:
        """Return the Git repo URL from the cached index or the default."""
        if self._cached_index and self._cached_index.repo_url:
            return self._cached_index.repo_url
        return DEFAULT_REPO_URL

    def _proxy_env(self) -> dict[str, str] | None:
        """Return env vars for subprocess proxy, or None to inherit."""
        if not self._proxy_url:
            return None
        env = os.environ.copy()
        env["http_proxy"] = self._proxy_url
        env["https_proxy"] = self._proxy_url
        return env

    def _git_proxy_args(self) -> list[str]:
        """Return ``-c http.proxy=...`` args for git commands, or empty list."""
        proxy = self._proxy_url
        return ["-c", f"http.proxy={proxy}"] if proxy else []

    async def _ensure_repo_cache(self) -> Path:
        """Ensure a shared bare clone of the plugin repo exists locally.

        On first call the repo is cloned as a bare repository.  On
        subsequent calls only ``git fetch`` is executed to pull the
        latest changes — no full re-clone required.
        """
        repo_url = self._resolve_repo_url()
        proxy_env = self._proxy_env()
        proxy_args = self._git_proxy_args()

        REPO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        bare_dir = REPO_CACHE_DIR / "repo.git"

        if (bare_dir / "HEAD").exists():
            # Update existing bare clone.
            fetch_cmd = ["git", *proxy_args, "-C", str(bare_dir), "fetch", "--depth", "1", "origin", "main"]
            logger.info("Updating cached plugin repository")
            await _run_async(fetch_cmd, timeout=GIT_CLONE_TIMEOUT, error_prefix="git fetch failed", env=proxy_env)
        else:
            # First time: bare clone.
            if bare_dir.exists():
                shutil.rmtree(bare_dir, ignore_errors=True)
            clone_cmd = [
                "git", *proxy_args,
                "clone", "--bare", "--depth", "1",
                "--filter=blob:none",
                repo_url, str(bare_dir),
            ]
            logger.info("Cloning plugin repository (bare)", extra={"repo": repo_url})
            await _run_async(clone_cmd, timeout=GIT_CLONE_TIMEOUT, error_prefix="git clone failed", env=proxy_env)

        return bare_dir

    async def clone_plugin(
        self,
        entry: PluginRegistryEntry,
        *,
        dest_dir: Path | None = None,
    ) -> Path:
        """Extract a single plugin from the shared repo cache.

        Uses the cached bare clone so that installing multiple plugins
        from the same registry only requires one network fetch.
        Returns the path to the extracted plugin directory ready for
        installation by *PluginManager.install_plugin_from_directory()*.
        """
        if not entry.path:
            raise ValueError(f"No path defined for plugin: {entry.plugin_id}")

        bare_dir = await self._ensure_repo_cache()
        proxy_env = self._proxy_env()

        dest = dest_dir or Path(tempfile.mkdtemp(prefix="magi-plugin-clone-"))
        dest.mkdir(parents=True, exist_ok=True)

        work_dir = dest / "_work"
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

        # Create a working tree from the bare cache — local clone, no network.
        # Use file:// protocol so --depth is honoured on local repos.
        # Skip --filter since the bare cache is already a partial clone.
        local_clone_cmd = [
            "git", "clone",
            "--depth", "1",
            "--sparse",
            "--no-hardlinks",
            f"file://{bare_dir}", str(work_dir),
        ]
        await _run_async(local_clone_cmd, timeout=30, error_prefix="local clone failed", env=proxy_env)

        # Sparse checkout: only materialise the plugin we need.
        sparse_cmd = ["git", "-C", str(work_dir), "sparse-checkout", "set", entry.path]
        await _run_async(sparse_cmd, timeout=30, error_prefix="git sparse-checkout failed", env=proxy_env)

        plugin_src = work_dir / entry.path
        if not plugin_src.is_dir():
            raise ValueError(f"Plugin path '{entry.path}' not found in repository")

        # Copy the plugin directory out.
        plugin_dest = dest / entry.plugin_id
        shutil.copytree(plugin_src, plugin_dest)
        shutil.rmtree(work_dir, ignore_errors=True)

        logger.info("Plugin source extracted", extra={"plugin_id": entry.plugin_id, "path": str(plugin_dest)})
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


async def _run_async(
    cmd: list[str],
    *,
    timeout: int,
    error_prefix: str,
    env: dict[str, str] | None = None,
) -> str:
    """Run a subprocess asynchronously without blocking the event loop."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"{error_prefix}: timed out after {timeout}s")
    if proc.returncode != 0:
        raise RuntimeError(
            f"{error_prefix} (exit {proc.returncode}): {stderr.decode().strip()}"
        )
    return stdout.decode()


def _version_newer(remote: str, local: str) -> bool:
    """Compare semver-style version strings (best-effort)."""
    try:
        remote_parts = [int(p) for p in remote.split(".")]
        local_parts = [int(p) for p in local.split(".")]
        return remote_parts > local_parts
    except (ValueError, AttributeError):
        return remote != local
