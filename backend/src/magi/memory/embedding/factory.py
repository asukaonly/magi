"""Compose vector storage once at the memory lifecycle boundary."""

import hashlib
import json

from ...config.memory_models import VectorStorageSettings
from .chroma_client import ChromaVectorClient
from .ports import VectorIndexFactory, VectorLayer
from .remote_index import RemoteVectorIndex
from .sqlite_factory import SqliteVectorIndexFactory
from .sqlite_projection import SqliteVectorProjectionRepository

_LAYERS: tuple[VectorLayer, ...] = ("l1", "l2_entities", "l2_edges", "l3", "l4")


class ChromaVectorIndexFactory:
    def __init__(self, settings: VectorStorageSettings, *, journal_db_path: str) -> None:
        options = settings.chroma
        identity = hashlib.sha256(
            json.dumps(
                {
                    "host": options.host,
                    "port": options.port,
                    "ssl": options.ssl,
                    "tenant": options.tenant,
                    "database": options.database,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        client = ChromaVectorClient(options)
        repository = SqliteVectorProjectionRepository(journal_db_path)
        self._indexes = {
            layer: RemoteVectorIndex(
                namespace=layer,
                backend_identity=f"chroma:{identity}",
                repository=repository,
                client=client,
                retry_interval=settings.reconcile_interval_seconds,
                request_timeout=settings.request_timeout_seconds,
                automatic_recovery=False,
            )
            for layer in _LAYERS
        }

    async def start_recovery(self) -> None:
        for index in self._indexes.values():
            await index.start_recovery()

    def create(self, layer: VectorLayer) -> RemoteVectorIndex:
        return self._indexes[layer]

    async def clear_all(self) -> None:
        for index in self._indexes.values():
            await index.retire()
        for index in self._indexes.values():
            await index.flush()

    async def close(self) -> None:
        for index in self._indexes.values():
            await index.close()


def build_vector_index_factory(
    settings: VectorStorageSettings, *, l1_db_path: str, memory_db_path: str
) -> VectorIndexFactory:
    if settings.backend == "chroma":
        return ChromaVectorIndexFactory(settings, journal_db_path=memory_db_path)
    return SqliteVectorIndexFactory(
        l1_db_path=settings.sqlite_path or l1_db_path,
        memory_db_path=settings.sqlite_path or memory_db_path,
    )
