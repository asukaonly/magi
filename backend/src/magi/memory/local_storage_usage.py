"""Filesystem implementation of local memory database footprint measurement."""

import asyncio
from pathlib import Path
import stat


class LocalMemoryStorageUsage:
    def __init__(self, database_paths: tuple[Path, ...]) -> None:
        self._paths = database_paths

    async def measure_bytes(self) -> int | None:
        return await asyncio.to_thread(self._measure)

    def _measure(self) -> int | None:
        total = 0
        seen: set[Path] = set()
        for database in self._paths:
            for suffix in ("", "-wal", "-shm"):
                path = Path(f"{database}{suffix}")
                try:
                    key = path.resolve(strict=False)
                    if key in seen:
                        continue
                    seen.add(key)
                    details = path.stat()
                    if not stat.S_ISREG(details.st_mode):
                        return None
                    total += details.st_size
                except FileNotFoundError:
                    continue
                except OSError:
                    return None
        return total
