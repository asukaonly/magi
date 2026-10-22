"""Composition and lifecycle for local SQLite vector indexes."""

from dataclasses import dataclass
from pathlib import Path

from ...core.sqlite import secure_compact_sqlite, sqlite_connection_async
from .ports import VectorIndex, VectorLayer
from .sqlite_vec_index import SqliteVecIndex


@dataclass(frozen=True, slots=True)
class _IndexSchema:
    registry: str
    entity_column: str
    prefix: str
    partition_column: str | None = None


_SCHEMAS: dict[VectorLayer, _IndexSchema] = {
    "l1": _IndexSchema("l1_event_chunk_vectors", "chunk_id", "l1_event_vec", "user_id"),
    "l2_entities": _IndexSchema("l2_entity_vectors", "entity_id", "l2_entity_vec"),
    "l2_edges": _IndexSchema("l2_edge_vectors", "entity_id", "l2_edge_vec"),
    "l3": _IndexSchema("l3_summary_chunk_vectors", "chunk_id", "l3_summary_chunk_vec"),
    "l4": _IndexSchema("l4_skill_chunk_vectors", "chunk_id", "l4_skill_chunk_vec"),
}


class SqliteVectorIndexFactory:
    def __init__(self, *, l1_db_path: str, memory_db_path: str) -> None:
        self._paths = {layer: l1_db_path if layer == "l1" else memory_db_path for layer in _SCHEMAS}
        self._indexes: dict[VectorLayer, VectorIndex] = {}

    def create(self, layer: VectorLayer) -> VectorIndex:
        if layer not in self._indexes:
            schema = _SCHEMAS[layer]
            self._indexes[layer] = SqliteVecIndex(
                db_path=self._paths[layer],
                registry_table=schema.registry,
                entity_column=schema.entity_column,
                vec_table_prefix=schema.prefix,
                partition_key_column=schema.partition_column,
            )
        return self._indexes[layer]

    async def clear_all(self) -> None:
        """Clear persisted indexes even if their memory layer is currently disabled."""
        cleared_paths: set[str] = set()
        for layer, schema in _SCHEMAS.items():
            path = self._paths[layer]
            if not Path(path).is_file():
                continue
            async with sqlite_connection_async(path, profile="readonly") as db:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ) as cursor:
                    names = {str(row[0]) for row in await cursor.fetchall()}
            if schema.registry in names or any(name.startswith(schema.prefix) for name in names):
                await self.create(layer).clear()
                cleared_paths.add(path)
        await self.close()
        for path in sorted(cleared_paths):
            await secure_compact_sqlite(path)

    async def close(self) -> None:
        for index in self._indexes.values():
            await index.close()
