from __future__ import annotations

import pytest

from magi.api.routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
    PersonaReferenceModel,
)
from magi.api.services import personality_generation
from magi.personality.reference_research.models import (
    ReferenceDossier,
    ReferenceIdentity,
    ReferenceSource,
)


def _context(intent: PersonaGenerationIntentModel) -> personality_generation._GenerationRunContext:
    return personality_generation._GenerationRunContext(
        description="Reference in ordinary conversation",
        target_language="English",
        current_config=None,
        llm_override=None,
        intent=intent,
        adapter_resolver=lambda *args, **kwargs: object(),
        adapter_factory=lambda *args, **kwargs: object(),
        stage_progress_callback=None,
    )


def _intent(
    *,
    source_kind: str = "fictional_reference",
    fidelity: str = "natural",
    preference: str = "auto",
) -> PersonaGenerationIntentModel:
    return PersonaGenerationIntentModel(
        source_kind=source_kind,
        reference=PersonaReferenceModel(
            source_kind=source_kind,
            name="Reference",
            work_title="Example Work" if source_kind == "fictional_reference" else None,
            context="User-provided observation" if source_kind == "private_person_reference" else None,
            user_confirmed=True,
        ),
        fidelity_level=fidelity,
        expression_level="high_contextual" if fidelity == "faithful" else "balanced",
        research={"preference": preference},
    )


@pytest.mark.asyncio
async def test_generation_never_researches_private_reference(monkeypatch) -> None:
    called = False

    async def fake_research(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        raise AssertionError("private reference must not use public research")

    monkeypatch.setattr(personality_generation, "research_reference", fake_research)
    dossier = await personality_generation._run_reference_research_stage(
        _context(_intent(source_kind="private_person_reference", fidelity="traits", preference="disabled")),
        None,
    )

    assert dossier is None
    assert called is False


@pytest.mark.asyncio
async def test_generation_uses_representative_research_for_sparse_natural_prior(monkeypatch) -> None:
    captured: dict[str, object] = {}
    expected = ReferenceDossier(
        reference_fingerprint="fingerprint",
        identity_status="verified",
        grounding_status="verified",
        research_level="representative",
        canonical_identity=ReferenceIdentity(
            source_kind="fictional_reference",
            name="Reference",
            work_title="Example Work",
        ),
        profile_dimensions={"ordinary_baseline": ["Understated in ordinary conversation."]},
        sources=[
            ReferenceSource(
                source_id="source-1",
                url="https://example.com/source",
                title="Source",
                domain="example.com",
            )
        ],
        coverage=0.8,
        sufficient=True,
    )

    async def fake_research(identity, **kwargs):  # type: ignore[no-untyped-def]
        captured["identity"] = identity
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(personality_generation, "research_reference", fake_research)
    result = await personality_generation._run_reference_research_stage(
        _context(_intent()),
        {
            "dimensions": {"ordinary_baseline": ["Weak prior"]},
            "volatility": "stable",
        },
    )

    assert result == expected
    assert captured["research_level"] == "representative"


@pytest.mark.asyncio
async def test_generation_still_researches_natural_reference_when_model_prior_is_complete(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_research(identity, **kwargs):  # type: ignore[no-untyped-def]
        captured["identity"] = identity
        captured.update(kwargs)
        return ReferenceDossier(
            reference_fingerprint="fingerprint",
            identity_status="verified",
            grounding_status="verified",
            research_level="representative",
            canonical_identity=identity,
            sufficient=True,
        )

    monkeypatch.setattr(personality_generation, "research_reference", fake_research)
    complete_prior = {
        "dimensions": {
            dimension: [f"Model-prior {dimension} claim"]
            for dimension in (
                "ordinary_baseline",
                "judgment_patterns",
                "speech_rhythm",
                "interaction_patterns",
                "signature_markers",
                "contrast_contexts",
                "version_notes",
            )
        },
        "volatility": "stable",
    }

    await personality_generation._run_reference_research_stage(
        _context(_intent()),
        complete_prior,
    )

    assert captured["research_level"] == "representative"


@pytest.mark.asyncio
async def test_faithful_generation_never_silently_downgrades_without_network() -> None:
    with pytest.raises(ValueError, match="requires public-source verification"):
        await personality_generation._run_reference_research_stage(
            _context(_intent(fidelity="faithful", preference="disabled")),
            None,
        )


@pytest.mark.asyncio
async def test_faithful_generation_rejects_insufficient_public_evidence(monkeypatch) -> None:
    async def fake_research(identity, **kwargs):  # type: ignore[no-untyped-def]
        _ = (identity, kwargs)
        return ReferenceDossier(
            reference_fingerprint="fingerprint",
            identity_status="unverified",
            grounding_status="insufficient",
            research_level="full",
            sufficient=False,
        )

    monkeypatch.setattr(personality_generation, "research_reference", fake_research)
    with pytest.raises(ValueError, match="insufficient for faithful"):
        await personality_generation._run_reference_research_stage(
            _context(_intent(fidelity="faithful")),
            None,
        )


def test_source_backed_profile_overrides_prior_dimension_and_keeps_source_ids() -> None:
    dossier = ReferenceDossier(
        reference_fingerprint="fingerprint",
        identity_status="verified",
        grounding_status="verified",
        research_level="representative",
        canonical_identity=ReferenceIdentity(
            source_kind="public_person_reference",
            name="Reference",
        ),
        profile_dimensions={"speech_rhythm": ["Verified speech rhythm."]},
        sources=[
            ReferenceSource(
                source_id="source-1",
                url="https://example.com/source",
                domain="example.com",
            )
        ],
        sufficient=True,
    )

    merged = personality_generation._merge_reference_profile_with_dossier(
        {"dimensions": {"speech_rhythm": ["Unverified prior rhythm."]}},
        dossier,
    )

    assert merged is not None
    assert merged["provenance_kind"] == "public_sources"
    assert merged["dimensions"]["speech_rhythm"] == ["Verified speech rhythm."]
    assert merged["source_ids"] == ["source-1"]
