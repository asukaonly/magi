from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.memory.embedding.vector_admin import build_embedding_config_preflight


async def _ready_counts(**counts: int) -> dict[str, int]:
    return {"l1": 0, "l2_entities": 0, "l2_edges": 0, "l3": 0, "l4": 0, **counts}


def _memory_layer(enabled: bool = True, vectors_enabled: bool = True):
    return SimpleNamespace(enabled=enabled, vectors_enabled=vectors_enabled)


def _config(*, provider_id: str, model: str, dimension: int, base_url: str):
    provider = SimpleNamespace(
        provider_type="openai",
        api_format="openai",
        base_url=base_url,
        services=SimpleNamespace(embedding=SimpleNamespace(base_url=base_url)),
    )
    return SimpleNamespace(
        memory=SimpleNamespace(
            embedding=SimpleNamespace(mode="remote"),
            l1=_memory_layer(),
            l2=_memory_layer(),
            l3=_memory_layer(),
            l4=_memory_layer(),
        ),
        llm=SimpleNamespace(
            selections={
                "embedding": SimpleNamespace(
                    provider_id=provider_id,
                    model=model,
                    embedding_dimension=dimension,
                )
            },
            providers={provider_id: provider},
        ),
    )


@pytest.mark.asyncio
async def test_embedding_preflight_warns_strong_for_model_identity_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.memory.embedding.vector_admin.collect_vector_ready_counts",
        lambda: _ready_counts(l1=2),
    )

    result = await build_embedding_config_preflight(
        current_config=_config(
            provider_id="openai",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
        ),
        proposed_config=_config(
            provider_id="openai",
            model="text-embedding-3-large",
            dimension=3072,
            base_url="https://api.openai.com/v1",
        ),
    )

    assert result["severity"] == "strong"
    assert result["requires_rebuild"] is True
    assert result["warnings"][0]["reason"] == "hard_identity_changed"
    assert result["warnings"][0]["layer"] == "l1"


@pytest.mark.asyncio
async def test_embedding_preflight_warns_soft_for_remote_provider_provenance_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.memory.embedding.vector_admin.collect_vector_ready_counts",
        lambda: _ready_counts(l1=1),
    )

    result = await build_embedding_config_preflight(
        current_config=_config(
            provider_id="openai",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
        ),
        proposed_config=_config(
            provider_id="openrouter",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://openrouter.ai/api/v1",
        ),
    )

    assert result["severity"] == "soft"
    assert result["requires_rebuild"] is False
    assert result["warnings"][0]["reason"] == "remote_provider_changed"


@pytest.mark.asyncio
async def test_embedding_preflight_ignores_layers_without_ready_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.memory.embedding.vector_admin.collect_vector_ready_counts",
        lambda: _ready_counts(),
    )

    result = await build_embedding_config_preflight(
        current_config=_config(
            provider_id="openai",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
        ),
        proposed_config=_config(
            provider_id="openai",
            model="text-embedding-3-large",
            dimension=3072,
            base_url="https://api.openai.com/v1",
        ),
    )

    assert result["severity"] == "none"
    assert result["warnings"] == []
