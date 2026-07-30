"""Remote plugin registry client.

Fetches plugin metadata from a JSON index hosted alongside plugin source
code in a single Git repository.  Individual plugins are installed by
downloading a tarball archive from GitHub and extracting only the needed
plugin subdirectory — no local git commands required.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

import httpx

from ..config import get_config
from . import package_files
from .dependency_installation import PluginInstallWorkflowTimeoutError
from .operation_execution import run_plugin_preparation_operation
from .contracts import PluginRegistryEntry, PluginRegistryIndex
from .registry_provenance import registry_install_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/asukaonly/magi-plugins/main/registry.json"
DEFAULT_REPO_URL = "https://github.com/asukaonly/magi-plugins.git"
INDEX_TIMEOUT = 30
INDEX_TOTAL_TIMEOUT = 60
TARBALL_TIMEOUT = 120  # seconds
INDEX_CACHE_TTL = 300  # 5 minutes
MAX_REGISTRY_INDEX_BYTES = 4 * 1024 * 1024
MAX_REGISTRY_TARBALL_BYTES = 64 * 1024 * 1024
INDEX_DISK_CACHE_RELATIVE_PATH = Path("registry") / "index.json"
REGISTRY_DISK_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PluginRegistrySnapshot:
    """One immutable-by-convention registry consent and download snapshot."""

    index: PluginRegistryIndex
    registry_url: str
    repo_url: str
    install_fingerprint: str
    official_source: bool


class PluginRegistryClient:
    """Client for the remote plugin registry backed by a Git repository."""

    def __init__(
        self,
        *,
        registry_url: str | None = None,
        cache_path: Path | None = None,
    ) -> None:
        config = get_config()
        configured_url = getattr(config.plugins, "registry_url", None)
        self._registry_url = registry_url or configured_url or DEFAULT_REGISTRY_URL
        self._disk_cache_path = cache_path
        self._cached_index: PluginRegistryIndex | None = None
        self._cache_timestamp: float = 0.0
        self._index_lock = asyncio.Lock()
        self._index_task: asyncio.Task[PluginRegistryIndex] | None = None
        self._cached_tarball: bytes | None = None
        self._cached_tarball_key: tuple[str, str] | None = None
        self._tarball_timestamp: float = 0.0
        self._tarball_lock = asyncio.Lock()

    @property
    def _proxy_url(self) -> str | None:
        """Read proxy URL from live config each time so runtime changes apply."""
        return get_config().network.proxy_url()

    @property
    def _resolved_disk_cache_path(self) -> Path:
        """Return the durable registry cache path."""
        if self._disk_cache_path is not None:
            return self._disk_cache_path

        from ..utils.runtime import get_runtime_paths

        return get_runtime_paths().plugins_cache_dir / INDEX_DISK_CACHE_RELATIVE_PATH

    def _http_client(self, *, timeout: int = INDEX_TIMEOUT) -> httpx.AsyncClient:
        """Create an httpx client with the configured proxy (if any)."""
        kwargs: dict = {"timeout": timeout, "follow_redirects": True}
        if self._proxy_url:
            kwargs["proxy"] = self._proxy_url
        return httpx.AsyncClient(**kwargs)

    async def fetch_index(
        self,
        *,
        force: bool = False,
        deadline_monotonic: float | None = None,
    ) -> PluginRegistryIndex:
        """Fetch the full plugin registry index, with memory and disk caching."""
        if deadline_monotonic is not None and deadline_monotonic <= time.monotonic():
            raise PluginInstallWorkflowTimeoutError(
                "Plugin installation exceeded the workflow time limit"
            )

        async with self._index_lock:
            index_task = self._index_task
            if index_task is None or index_task.done():
                self._index_task = None
                now = time.monotonic()
                if (
                    not force
                    and self._cached_index is not None
                    and (now - self._cache_timestamp) < INDEX_CACHE_TTL
                ):
                    return self._cached_index

                index_task = asyncio.create_task(self._fetch_and_cache_index())
                self._index_task = index_task
                index_task.add_done_callback(self._clear_index_task)

        return await self._await_index_task(
            index_task,
            deadline_monotonic=deadline_monotonic,
        )

    async def _fetch_and_cache_index(self) -> PluginRegistryIndex:
        """Fetch one shared registry result and update the local caches."""

        try:
            index = await self._fetch_remote_index()
        except Exception:
            cached_index = await run_plugin_preparation_operation(self._read_disk_cache)
            if cached_index is None:
                raise
            logger.warning(
                "Using cached plugin registry after remote fetch failed",
                extra={"cache_path": str(self._resolved_disk_cache_path)},
                exc_info=True,
            )
            self._cached_index = cached_index
            self._cache_timestamp = time.monotonic()
            return cached_index

        self._cached_index = index
        self._cache_timestamp = time.monotonic()
        await run_plugin_preparation_operation(lambda: self._write_disk_cache(index))
        return index

    def _clear_index_task(self, index_task: asyncio.Task[PluginRegistryIndex]) -> None:
        """Release a completed shared request and observe any unclaimed failure."""

        if self._index_task is index_task:
            self._index_task = None
        if index_task.cancelled():
            return
        index_task.exception()

    async def _await_index_task(
        self,
        index_task: asyncio.Task[PluginRegistryIndex],
        *,
        deadline_monotonic: float | None,
    ) -> PluginRegistryIndex:
        """Await a shared request without letting one caller cancel it."""

        shared_result = asyncio.shield(index_task)
        if deadline_monotonic is None:
            return await shared_result

        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise PluginInstallWorkflowTimeoutError(
                "Plugin installation exceeded the workflow time limit"
            )
        try:
            return await asyncio.wait_for(shared_result, timeout=remaining)
        except asyncio.TimeoutError as exc:
            if index_task.done():
                return index_task.result()
            raise PluginInstallWorkflowTimeoutError(
                "Plugin installation exceeded the workflow time limit"
            ) from exc

    async def _fetch_remote_index(
        self,
        *,
        deadline_monotonic: float | None = None,
    ) -> PluginRegistryIndex:
        """Fetch and validate the remote registry index."""

        timeout = float(INDEX_TOTAL_TIMEOUT)
        if deadline_monotonic is not None:
            timeout = min(timeout, deadline_monotonic - time.monotonic())
        if timeout <= 0:
            raise PluginInstallWorkflowTimeoutError(
                "Plugin installation exceeded the workflow time limit"
            )
        try:
            payload = await asyncio.wait_for(
                self._download_remote_index(),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                "Plugin registry index exceeded the total download time limit"
            ) from exc
        return await run_plugin_preparation_operation(
            lambda: PluginRegistryIndex.model_validate_json(payload)
        )

    async def _download_remote_index(self) -> bytes:
        """Download one bounded registry index payload."""

        payload = bytearray()
        async with self._http_client() as client:
            async with client.stream("GET", self._registry_url) as response:
                response.raise_for_status()
                _reject_oversized_content_length(
                    response.headers.get("content-length"),
                    limit=MAX_REGISTRY_INDEX_BYTES,
                    label="Plugin registry index",
                )
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_REGISTRY_INDEX_BYTES:
                        raise ValueError("Plugin registry index exceeds the download limit")
        return bytes(payload)

    def _read_disk_cache(self) -> PluginRegistryIndex | None:
        """Read a previously successful registry response from disk."""
        cache_path = self._resolved_disk_cache_path
        if not cache_path.exists():
            return None
        try:
            with cache_path.open("rb") as cache_file:
                payload = cache_file.read(MAX_REGISTRY_INDEX_BYTES + 1)
            if len(payload) > MAX_REGISTRY_INDEX_BYTES:
                raise ValueError("Plugin registry disk cache exceeds the size limit")
            envelope = json.loads(payload)
            if (
                not isinstance(envelope, dict)
                or envelope.get("schema_version") != REGISTRY_DISK_CACHE_SCHEMA_VERSION
                or envelope.get("registry_url") != self._registry_url
            ):
                raise ValueError("Plugin registry disk cache source does not match")
            return PluginRegistryIndex.model_validate(envelope.get("index"))
        except Exception:
            logger.warning(
                "Ignoring invalid plugin registry disk cache",
                extra={"cache_path": str(cache_path)},
                exc_info=True,
            )
            return None

    def _write_disk_cache(self, index: PluginRegistryIndex) -> None:
        """Persist a validated registry response for offline fallback."""
        cache_path = self._resolved_disk_cache_path
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
            payload = json.dumps(
                {
                    "schema_version": REGISTRY_DISK_CACHE_SCHEMA_VERSION,
                    "registry_url": self._registry_url,
                    "index": index.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            if len(payload) > MAX_REGISTRY_INDEX_BYTES:
                raise ValueError("Plugin registry index exceeds the disk cache limit")
            tmp_path.write_bytes(payload)
            tmp_path.replace(cache_path)
        except Exception:
            logger.warning(
                "Failed to write plugin registry disk cache",
                extra={"cache_path": str(cache_path)},
                exc_info=True,
            )

    async def fetch_entry(self, plugin_id: str) -> PluginRegistryEntry | None:
        """Fetch a single plugin entry from the registry."""
        index = self._cached_index or await self.fetch_index()
        for entry in index.plugins:
            if entry.plugin_id == plugin_id:
                return entry
        return None

    async def fetch_snapshot(
        self,
        *,
        force: bool = False,
        deadline_monotonic: float | None = None,
    ) -> PluginRegistrySnapshot:
        """Return one host-fingerprinted registry snapshot."""

        index = await self.fetch_index(
            force=force,
            deadline_monotonic=deadline_monotonic,
        )
        repo_url = index.repo_url or DEFAULT_REPO_URL
        return PluginRegistrySnapshot(
            index=index,
            registry_url=self._registry_url,
            repo_url=repo_url,
            install_fingerprint=registry_install_fingerprint(
                index,
                registry_url=self._registry_url,
                repo_url=repo_url,
            ),
            official_source=is_official_registry_source(self._registry_url, repo_url),
        )

    @staticmethod
    def _tarball_url(repo_url: str, ref: str = "main") -> str:
        """Build the GitHub tarball URL from the repo URL."""
        # https://github.com/owner/repo.git → https://api.github.com/repos/owner/repo/tarball/main
        base = repo_url.removesuffix(".git").rstrip("/")
        if "github.com/" in base:
            parts = base.split("github.com/", 1)[1]
            return f"https://api.github.com/repos/{parts}/tarball/{ref}"
        # Non-GitHub: fall back to raw URL + archive convention.
        return f"{base}/archive/{ref}.tar.gz"

    async def _fetch_tarball(
        self,
        snapshot: PluginRegistrySnapshot,
        *,
        deadline_monotonic: float | None = None,
    ) -> bytes:
        """Download the repo tarball, with short-lived in-memory caching.

        When multiple plugins are installed back-to-back (e.g. during
        onboarding), only one HTTP download is performed.
        """
        tarball_url = self._tarball_url(snapshot.repo_url)
        cache_key = (tarball_url, snapshot.install_fingerprint)
        now = time.monotonic()
        if (
            self._cached_tarball is not None
            and self._cached_tarball_key == cache_key
            and (now - self._tarball_timestamp) < INDEX_CACHE_TTL
        ):
            return self._cached_tarball

        async def fetch_under_lock() -> bytes:
            async with self._tarball_lock:
                now = time.monotonic()
                if (
                    self._cached_tarball is not None
                    and self._cached_tarball_key == cache_key
                    and (now - self._tarball_timestamp) < INDEX_CACHE_TTL
                ):
                    return self._cached_tarball

                payload = await self._download_tarball(tarball_url)
                self._cached_tarball = payload
                self._cached_tarball_key = cache_key
                self._tarball_timestamp = time.monotonic()
                return payload

        if deadline_monotonic is None:
            return await fetch_under_lock()
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise PluginInstallWorkflowTimeoutError(
                "Plugin installation exceeded the workflow time limit"
            )
        try:
            # This awaits cancellation of the HTTP coroutine before returning,
            # so a timed-out workflow does not leave a download running.
            return await asyncio.wait_for(fetch_under_lock(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise PluginInstallWorkflowTimeoutError(
                "Plugin installation exceeded the workflow time limit"
            ) from exc

    async def _download_tarball(self, tarball_url: str) -> bytes:
        """Download one bounded tarball payload."""

        logger.info("Downloading plugin repository tarball", extra={"url": tarball_url})
        payload = bytearray()
        async with self._http_client(timeout=TARBALL_TIMEOUT) as client:
            async with client.stream("GET", tarball_url) as response:
                response.raise_for_status()
                _reject_oversized_content_length(
                    response.headers.get("content-length"),
                    limit=MAX_REGISTRY_TARBALL_BYTES,
                    label="Plugin registry tarball",
                )
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_REGISTRY_TARBALL_BYTES:
                        raise ValueError("Plugin registry tarball exceeds the download limit")
        result = bytes(payload)
        logger.info(
            "Downloaded plugin repository tarball",
            extra={"url": tarball_url, "bytes": len(result)},
        )
        return result

    async def clone_plugin(
        self,
        entry: PluginRegistryEntry,
        *,
        snapshot: PluginRegistrySnapshot,
        dest_dir: Path | None = None,
        deadline_monotonic: float | None = None,
    ) -> Path:
        """Download and extract a single plugin from the remote repository.

        Downloads the repo tarball from GitHub (cached for repeat calls),
        then extracts only the plugin subdirectory.  No local git
        commands are required.

        Returns the path to the extracted plugin directory ready for
        installation by *PluginManager.install_plugin_from_directory()*.
        """
        if not entry.path:
            raise ValueError(f"No path defined for plugin: {entry.plugin_id}")

        dest = dest_dir or Path(tempfile.mkdtemp(prefix="magi-plugin-dl-"))
        dest.mkdir(parents=True, exist_ok=True)

        try:
            logger.info(
                "Cloning plugin from registry tarball",
                extra={
                    "plugin_id": entry.plugin_id,
                    "registry_path": entry.path,
                    "dest_dir": str(dest),
                },
            )
            tarball_bytes = await self._fetch_tarball(
                snapshot,
                deadline_monotonic=deadline_monotonic,
            )

            plugin_dest = dest / entry.plugin_id
            await run_plugin_preparation_operation(
                lambda: _extract_subdir_from_tarball(
                    tarball_bytes,
                    entry.path,
                    plugin_dest,
                )
            )

            logger.info(
                "Plugin source extracted",
                extra={"plugin_id": entry.plugin_id, "path": str(plugin_dest)},
            )
            return plugin_dest
        except Exception:
            logger.exception(
                "Plugin source extraction failed",
                extra={
                    "plugin_id": entry.plugin_id,
                    "registry_path": entry.path,
                    "dest_dir": str(dest),
                },
            )
            # Clean up on failure.
            if dest_dir is None:
                await run_plugin_preparation_operation(
                    lambda: shutil.rmtree(dest, ignore_errors=True)
                )
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
    """Extract one registry package through the shared safe archive planner."""

    package_files.extract_plugin_subdirectory_tarball(
        tarball_bytes,
        subdir,
        dest,
    )


def _reject_oversized_content_length(
    raw_content_length: str | None,
    *,
    limit: int,
    label: str,
) -> None:
    if raw_content_length is None:
        return
    try:
        content_length = int(raw_content_length)
    except ValueError:
        return
    if content_length > limit:
        raise ValueError(f"{label} exceeds the download limit")


def _normalize_repo_url(repo_url: str) -> str:
    return repo_url.strip().rstrip("/").removesuffix(".git").casefold()


def is_official_registry_source(registry_url: str | None, repo_url: str | None) -> bool:
    """Return whether an unsigned registry may assert Magi official status."""

    return bool(
        registry_url == DEFAULT_REGISTRY_URL
        and repo_url
        and _normalize_repo_url(repo_url) == _normalize_repo_url(DEFAULT_REPO_URL)
    )


def _version_newer(remote: str, local: str) -> bool:
    """Compare semver-style version strings (best-effort)."""
    try:
        remote_parts = [int(p) for p in remote.split(".")]
        local_parts = [int(p) for p in local.split(".")]
        return remote_parts > local_parts
    except (ValueError, AttributeError):
        return remote != local
