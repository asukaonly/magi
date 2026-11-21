"""Tests for out-of-the-box local ONNX embedding activation, backfill, and FTS fallback."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from _shared.memory_stores import build_memory_store
from magi.api.routers import local_embedding as router_mod
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    LocalEmbeddingModelRegistry,
    LocalEmbeddingVariantMeta,
    get_local_embedding_registry,
)
from magi.config.memory_models import EmbeddingMode, EmbeddingSettings
from magi.memory.embedding.embedding_service import EmbeddingResult, MemoryEmbeddingService
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.hybrid_retrieval.models import RetrievalConfig, RetrievalQuery
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.unified_store import MemoryStoreTuning


def test_example_config_matches_embedding_default_and_registry_has_recommended_preset() -> None:
    example_path = Path(__file__).resolve().parents[2] / "configs" / "config.example.yaml"
    example_data = yaml.safe_load(example_path.read_text(encoding="utf-8"))
    assert example_data["agent"]["memory"]["embedding"]["mode"] == EmbeddingSettings().mode.value
    assert get_local_embedding_registry().recommended_default_id() == "bge-small-zh-v1.5"


@pytest.mark.asyncio
async def test_auto_enable_download_activates_local_model_and_triggers_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta = LocalEmbeddingModelMeta(
        id="bge-small-zh-v1.5",
        label="BGE Small Chinese v1.5",
        repo="BAAI/bge-small-zh-v1.5",
        onnx_repo="onnx-community/bge-small-zh-v1.5-ONNX",
        dimension=512,
        max_tokens=512,
        recommended=True,
        variants={
            "quantized": LocalEmbeddingVariantMeta(file="onnx/model_quantized.onnx", size_mb=24),
        },
        default_variant={"_fallback": "quantized"},
    )
    registry = LocalEmbeddingModelRegistry(models=[meta])
    model_dir = tmp_path / "embed" / meta.id
    paths = MagicMock()
    paths.managed_embedding_model_dir.return_value = str(model_dir)

    saved_updates: dict[str, object] = {}

    def fake_save_config(updates: dict[str, object]) -> bool:
        saved_updates.update(updates)
        return True

    async def fake_download(repo_id, patterns, local_dir, tracker, proxy_url):
        target = Path(local_dir) / "onnx"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model_quantized.onnx").write_bytes(b"onnx-bytes")
        (Path(local_dir) / "tokenizer.json").write_text("{}", encoding="utf-8")
        return str(local_dir)

    fake_memory = SimpleNamespace(name="unified_memory")
    fake_rebuild_manager = MagicMock()
    fake_rebuild_manager.start_rebuild = AsyncMock(return_value={"job_id": "job-1", "status": "running"})

    fake_cfg = SimpleNamespace(
        network=SimpleNamespace(proxy_url=lambda: None),
        agent=SimpleNamespace(
            memory=SimpleNamespace(
                embedding=SimpleNamespace(
                    mode=EmbeddingMode.LOCAL,
                    local=SimpleNamespace(managed_model_id=meta.id),
                )
            )
        ),
    )

    tasks: dict[str, asyncio.Task[None]] = {}
    monkeypatch.setattr(router_mod, "get_local_embedding_registry", lambda: registry)
    monkeypatch.setattr(router_mod, "RuntimePaths", lambda: paths)
    monkeypatch.setattr(router_mod, "_download_progress", {})
    monkeypatch.setattr(router_mod, "_download_tasks", tasks)
    monkeypatch.setattr(router_mod, "_download_errors", {})
    monkeypatch.setattr(router_mod, "_download_auto_enable", set())
    monkeypatch.setattr(router_mod, "download_hub_model", fake_download)
    monkeypatch.setattr(router_mod, "save_config", fake_save_config)
    monkeypatch.setattr(router_mod, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(router_mod.memory_dependencies, "_resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr(router_mod, "get_embedding_rebuild_manager", lambda: fake_rebuild_manager)

    app = FastAPI()
    app.include_router(
        _build_public_router(
            router_mod.local_embedding_router, _PUBLIC_ROUTE_METHODS["local_embedding"]
        ),
        prefix="/api/local-embedding",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/local-embedding/models/{meta.id}/download",
            params={"auto_enable": "true"},
        )
        assert response.status_code == 200
        await asyncio.wait_for(tasks[meta.id], timeout=3)

    assert saved_updates["agent.memory.embedding.mode"] == "local"
    assert saved_updates["agent.memory.embedding.local.model_source"] == "managed"
    assert saved_updates["agent.memory.embedding.local.managed_model_id"] == meta.id
    fake_rebuild_manager.start_rebuild.assert_awaited_once_with(unified_memory=fake_memory)


@pytest.mark.asyncio
async def test_cross_term_semantic_retrieval_and_clean_fts_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SemanticEmbeddingService:
        async def embed_text(self, text: str) -> EmbeddingResult:
            lowered = text.lower()
            if "piano" in lowered or "relaxing song" in lowered:
                vec = [0.99, 0.14, 0.0, 0.0]
            else:
                vec = [0.0, 0.0, 0.99, 0.14]
            return EmbeddingResult(
                model_name="bge-small-zh-v1.5",
                dimension=4,
                vector=vec,
                model_identity="local:onnx:test-hash",
            )

        async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
            return [await self.embed_text(t) for t in texts]

        def result_for_index(
            self,
            result: EmbeddingResult,
            *,
            text_builder_version: str,
        ) -> EmbeddingResult:
            profile = self.profile_from_result(result, text_builder_version=text_builder_version)
            return EmbeddingResult(
                model_name=result.model_name,
                dimension=result.dimension,
                vector=result.vector,
                model_identity=result.model_identity,
                index_identity=profile.profile_id,
            )

        def profile_from_result(self, result: EmbeddingResult, *, text_builder_version: str):
            from magi_plugin_sdk.storage_models.embedding_profile import EmbeddingProfile

            return EmbeddingProfile.build(
                provider_name="local",
                model_name=result.model_name,
                dimension=result.dimension,
                text_builder_version=text_builder_version,
                identity_kind="local",
                identity_key=result.model_identity or result.model_name,
            )

        def get_active_profile(self, *, text_builder_version: str):
            from magi_plugin_sdk.storage_models.embedding_profile import EmbeddingProfile

            return EmbeddingProfile.build(
                provider_name="local",
                model_name="bge-small-zh-v1.5",
                dimension=4,
                text_builder_version=text_builder_version,
                identity_kind="local",
                identity_key="local:onnx:test-hash",
            )

    store = build_memory_store(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        archive_dir_path=str(tmp_path / "archive"),
        embedding_service=_SemanticEmbeddingService(),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=True,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            async_embeddings=False,
        ),
    )
    await store.initialize(start_workers=False)
    try:
        event_id = "evt-piano-semantic"
        await store.l1.store(
            MemoryEvent(
                event_id=event_id,
                correlation_id="corr-sem",
                timestamp=1_700_000_000.0,
                created_at=1_700_000_000.0,
                event_type="SensorEvent",
                source="netease_music",
                source_item_id="track-piano",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="local_user",
                task_id=None,
                content="Listened to a quiet piano piece late at night",
                author_type="external",
                content_type="observation",
                importance_score=0.7,
                level=20,
                idempotency_key="netease_music:track-piano",
            )
        )
        # Verify cross-term query ("relaxing song" has zero lexical overlap with "quiet piano piece")
        # resolves cleanly via sqlite-vec semantic similarity.
        retrieval = HybridRetrievalService(
            store,
            config=RetrievalConfig(
                intent_decider_llm_enabled=False,
                query_expansion_enabled=False,
            ),
        )
        semantic_hits = await retrieval.query(
            RetrievalQuery(
                query="that relaxing song",
                user_id="local_user",
                limit=5,
            )
        )
        assert any(item["event_id"] == event_id for item in semantic_hits.l1_events)

        # Verify missing/failed local model files cleanly return None profile & FTS still works.
        missing_cfg = SimpleNamespace(
            agent=SimpleNamespace(
                memory=SimpleNamespace(
                    embedding=SimpleNamespace(
                        mode=EmbeddingMode.LOCAL,
                        local=SimpleNamespace(
                            model_source="managed",
                            managed_model_id="missing-model-id",
                            model_dir_path=None,
                            variant=None,
                            idle_timeout_seconds=1800,
                        ),
                    )
                )
            )
        )
        monkeypatch.setattr("magi.memory.embedding.embedding_service.get_config", lambda: missing_cfg)
        real_service = MemoryEmbeddingService(None)
        assert real_service.get_active_profile(text_builder_version="l1_v1") is None

        fts_hits = await store.l1.query_events(query="piano", limit=5)
        assert any(item["event_id"] == event_id for item in fts_hits)
    finally:
        await store.shutdown()
