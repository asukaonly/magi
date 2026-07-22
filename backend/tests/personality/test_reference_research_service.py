from __future__ import annotations

from typing import Any

import pytest

from magi.personality.reference_research.models import ReferenceIdentity, ReferenceSource
from magi.personality.reference_research import service


class _SearchPort:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [
            {
                "title": "Reference official interview",
                "url": "https://example.com/interview",
                "snippet": "A first-person interview about ordinary decisions.",
            },
            {
                "title": "Reference profile",
                "url": "https://example.org/profile",
                "snippet": "A background profile.",
            },
            {
                "title": "Reference dialogue archive",
                "url": "https://archive.example.net/dialogue",
                "snippet": "Dialogue and scene context.",
            },
        ][:limit]


class _FetchPort:
    def __init__(self, *, empty: bool = False) -> None:
        self.urls: list[str] = []
        self.empty = empty

    async def fetch(self, url: str, *, max_chars: int = 12000) -> dict[str, Any]:
        self.urls.append(url)
        return {} if self.empty else {"title": "Fetched source", "content": f"Evidence from {url}"}


class _SameDomainSearchPort:
    async def search(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        _ = query
        return [
            {
                "title": f"Reference source {index}",
                "url": f"https://example.com/source-{index}",
                "snippet": "Behavioral evidence.",
            }
            for index in range(1, 5)
        ][:limit]


@pytest.mark.asyncio
async def test_identity_verification_returns_reviewable_ambiguity(monkeypatch) -> None:
    responses = [{
        "status": "ambiguous",
        "confidence": 0.61,
        "canonical_identity": {
            "source_kind": "fictional_reference",
            "name": "孙悟空",
            "work_title": "西游记",
        },
        "alternatives": [{
            "source_kind": "fictional_reference",
            "name": "孙悟空",
            "work_title": "龙珠",
        }],
        "supporting_source_ids": ["source-1"],
    }]

    async def fake_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return responses.pop(0)

    monkeypatch.setattr(service, "_run_json_llm", fake_llm)
    search = _SearchPort()
    fetch = _FetchPort()
    result = await service.verify_reference_identity(
        ReferenceIdentity(
            source_kind="fictional_reference",
            name="孙悟空",
        ),
        target_language="Chinese",
        search_port=search,
        fetch_port=fetch,
    )

    assert result.status == "ambiguous"
    assert result.requires_confirmation is True
    assert result.canonical_identity is not None
    assert result.canonical_identity.work_title == "西游记"
    assert result.alternatives[0].work_title == "龙珠"
    assert len(result.sources) >= 1
    assert search.queries
    assert fetch.urls


@pytest.mark.asyncio
async def test_research_dossier_drops_claims_without_valid_sources(monkeypatch) -> None:
    responses = [
        {"queries": ["Reference ordinary behavior", "Reference transcript"]},
        {
            "canonical_identity": {
                "source_kind": "public_person_reference",
                "name": "Reference",
            },
            "identity_status": "verified",
            "volatility": "evolving",
            "evidence": [
                {
                    "dimension": "ordinary_baseline",
                    "claim": "Keeps ordinary exchanges understated.",
                    "source_ids": ["source-1"],
                    "confidence": 0.8,
                },
                {
                    "dimension": "signature_markers",
                    "claim": "Invented unsupported catchphrase.",
                    "source_ids": ["missing-source"],
                    "confidence": 0.9,
                },
            ],
            "unknowns": ["Long-term private relationships"],
            "contradictions": [],
        },
    ]

    async def fake_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return responses.pop(0)

    monkeypatch.setattr(service, "_run_json_llm", fake_llm)
    result = await service.research_reference(
        ReferenceIdentity(
            source_kind="public_person_reference",
            name="Reference",
        ),
        research_level="representative",
        target_language="English",
        search_port=_SearchPort(),
        fetch_port=_FetchPort(),
        force_refresh=True,
    )

    assert [item.claim for item in result.evidence] == ["Keeps ordinary exchanges understated."]
    assert result.profile_dimensions["ordinary_baseline"] == ["Keeps ordinary exchanges understated."]
    assert result.profile_dimensions["signature_markers"] == []
    assert result.volatility == "evolving"
    assert result.sources


@pytest.mark.asyncio
async def test_research_dossier_reports_unavailable_fetches(monkeypatch) -> None:
    async def fake_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {"queries": ["Reference identity"]}

    monkeypatch.setattr(service, "_run_json_llm", fake_llm)
    result = await service.research_reference(
        ReferenceIdentity(
            source_kind="fictional_reference",
            name="Reference",
        ),
        research_level="full",
        target_language="English",
        search_port=_SearchPort(),
        fetch_port=_FetchPort(empty=True),
        force_refresh=True,
    )

    assert result.grounding_status == "unavailable"
    assert result.sufficient is False
    assert result.warning


@pytest.mark.asyncio
async def test_source_fetch_prefers_independent_domains() -> None:
    sources = [
        ReferenceSource(
            source_id="source-1",
            url="https://example.com/one",
            domain="example.com",
            authority=0.9,
            directness=0.9,
        ),
        ReferenceSource(
            source_id="source-2",
            url="https://example.com/two",
            domain="example.com",
            authority=0.8,
            directness=0.8,
        ),
        ReferenceSource(
            source_id="source-3",
            url="https://example.org/three",
            domain="example.org",
            authority=0.5,
            directness=0.5,
        ),
    ]
    fetch = _FetchPort()

    await service._fetch_sources(sources, fetch, limit=2)

    assert fetch.urls == ["https://example.com/one", "https://example.org/three"]


@pytest.mark.asyncio
async def test_full_dossier_requires_more_than_one_source_domain(monkeypatch) -> None:
    evidence = [
        {
            "dimension": dimension,
            "claim": f"Supported {dimension} claim.",
            "source_ids": [f"source-{(index % 3) + 1}"],
            "confidence": 0.8,
        }
        for index, dimension in enumerate(service._PROFILE_DIMENSIONS)
    ]
    responses = [
        {"queries": ["Reference profile", "Reference interview"]},
        {
            "canonical_identity": {
                "source_kind": "fictional_reference",
                "name": "Reference",
            },
            "identity_status": "verified",
            "volatility": "stable",
            "evidence": evidence,
            "unknowns": [],
            "contradictions": [],
        },
    ]

    async def fake_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return responses.pop(0)

    monkeypatch.setattr(service, "_run_json_llm", fake_llm)
    result = await service.research_reference(
        ReferenceIdentity(
            source_kind="fictional_reference",
            name="Reference",
        ),
        research_level="full",
        target_language="English",
        search_port=_SameDomainSearchPort(),
        fetch_port=_FetchPort(),
        force_refresh=True,
    )

    assert result.coverage == 1.0
    assert len(result.sources) >= 3
    assert result.sufficient is False
    assert result.grounding_status == "insufficient"


def test_reference_fingerprint_changes_with_work_identity() -> None:
    first = service.build_reference_fingerprint(
        ReferenceIdentity(
            source_kind="fictional_reference",
            name="孙悟空",
            work_title="西游记",
        )
    )
    second = service.build_reference_fingerprint(
        ReferenceIdentity(
            source_kind="fictional_reference",
            name="孙悟空",
            work_title="龙珠",
        )
    )

    assert first != second
