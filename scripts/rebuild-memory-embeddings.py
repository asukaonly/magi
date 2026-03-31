#!/usr/bin/env python3
"""Rebuild persisted memory embeddings from parent rows."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_SRC_DIR = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC_DIR))

from magi.config import get_config  # noqa: E402
from magi.llm.factory import create_scenario_llm_pool  # noqa: E402
from magi.memory.embedding.embedding_service import MemoryEmbeddingService  # noqa: E402
from magi.memory.l1.event_store import L1EventStore  # noqa: E402
from magi.memory.l2.entity_catalog import L2EntityCatalog  # noqa: E402
from magi.memory.l3.summary_store import L3SummaryStore  # noqa: E402
from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore  # noqa: E402
from magi.utils.runtime import get_runtime_paths, set_runtime_dir  # noqa: E402

VALID_LAYERS = ("l1", "l2", "l3", "l4")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild Magi memory embeddings.")
    parser.add_argument(
        "--layers",
        default="all",
        help="Comma-separated layers to rebuild: l1,l2,l3,l4 or all.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="How many parent rows to rebuild per batch.",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Optional Magi runtime home override (defaults to ~/.magi).",
    )
    return parser.parse_args()


def _resolve_layers(raw_value: str) -> list[str]:
    normalized = [part.strip().lower() for part in str(raw_value or "all").split(",") if part.strip()]
    if not normalized or normalized == ["all"]:
        return list(VALID_LAYERS)
    invalid = [layer for layer in normalized if layer not in VALID_LAYERS]
    if invalid:
        raise SystemExit(f"Unsupported layer selection: {', '.join(invalid)}")
    ordered: list[str] = []
    for layer in normalized:
        if layer not in ordered:
            ordered.append(layer)
    return ordered


async def _run() -> int:
    args = _parse_args()
    if args.base_dir:
        set_runtime_dir(args.base_dir)
    runtime_paths = get_runtime_paths()
    config = get_config()
    memory_cfg = config.agent.memory
    batch_size = max(1, int(args.batch_size))
    selected_layers = _resolve_layers(args.layers)

    llm_pool = create_scenario_llm_pool(config)
    embedding_service = MemoryEmbeddingService(llm_pool)

    results: dict[str, int | str] = {}

    if "l1" in selected_layers:
        if not memory_cfg.l1.enabled or not memory_cfg.l1.vectors_enabled:
            results["l1"] = "skipped (disabled in config)"
        else:
            store = L1EventStore(
                db_path=str(runtime_paths.l1_memory_db_path),
                embedding_service=embedding_service,
                memory_config_getter=lambda: get_config().agent.memory,
                vector_enabled=True,
                async_embeddings=False,
            )
            await store.initialize()
            try:
                results["l1"] = await store.rebuild_embeddings(batch_size=batch_size)
            finally:
                await store.shutdown()

    if "l2" in selected_layers:
        if not memory_cfg.l2.enabled or not memory_cfg.l2.vectors_enabled:
            results["l2"] = "skipped (disabled in config)"
        else:
            catalog = L2EntityCatalog(
                db_path=str(runtime_paths.memory_db_path),
                embedding_service=embedding_service,
                memory_config_getter=lambda: get_config().agent.memory,
                vector_enabled=True,
            )
            await catalog.initialize()
            try:
                results["l2"] = await catalog.rebuild_embeddings(batch_size=batch_size)
            finally:
                await catalog.close()

    if "l3" in selected_layers:
        if not memory_cfg.l3.enabled or not memory_cfg.l3.vectors_enabled:
            results["l3"] = "skipped (disabled in config)"
        else:
            store = L3SummaryStore(
                db_path=str(runtime_paths.memory_db_path),
                embedding_service=embedding_service,
                memory_config_getter=lambda: get_config().agent.memory,
                vector_enabled=True,
                async_embeddings=False,
                enable_temporal_llm_summary=memory_cfg.l3.llm_summary_enabled,
                temporal_llm_timeout_seconds=memory_cfg.l3.temporal_llm_timeout_seconds,
                temporal_llm_min_event_count=memory_cfg.l3.temporal_llm_min_event_count,
            )
            await store.initialize()
            try:
                results["l3"] = await store.rebuild_embeddings(batch_size=batch_size)
            finally:
                await store.shutdown()

    if "l4" in selected_layers:
        if not memory_cfg.l4.enabled or not memory_cfg.l4.vectors_enabled:
            results["l4"] = "skipped (disabled in config)"
        else:
            store = L4ProceduralMemoryStore(
                db_path=str(runtime_paths.memory_db_path),
                embedding_service=embedding_service,
                memory_config_getter=lambda: get_config().agent.memory,
                vector_enabled=True,
                async_embeddings=False,
            )
            await store.initialize()
            try:
                results["l4"] = await store.rebuild_embeddings(batch_size=batch_size)
            finally:
                await store.shutdown()

    print(f"Memory home: {runtime_paths.base_dir}")
    for layer in VALID_LAYERS:
        if layer in results:
            print(f"{layer}: {results[layer]}")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
