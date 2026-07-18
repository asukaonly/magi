"""Extension boundary for source domains affected by durable forgetting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..source_event_governance import normalize_source_event_ids
from .models import SelectorKind


class SourceForgetOwnerUnavailableError(RuntimeError):
    """A required source owner has not joined the runtime yet."""


@dataclass(frozen=True, slots=True)
class SourceForgetIdentity:
    """Raw L1 ownership captured while the forget selection is stable."""

    event_id: str
    source: str
    source_item_id: str


@dataclass(frozen=True, slots=True)
class SourceForgetBatch:
    """One source-specific selection page presented to its owner."""

    operation_id: str
    selector_kind: SelectorKind
    identities: tuple[SourceForgetIdentity, ...]
    reason: str
    block_source_item: bool


@dataclass(frozen=True, slots=True)
class SourceForgetClaim:
    """Durable source obligation plus every current event it owns."""

    source: str
    source_item_id: str
    event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized_source = str(self.source or "").strip()
        normalized_item = str(self.source_item_id or "").strip()
        if not normalized_source or not normalized_item:
            raise ValueError("Source-forget claim identity must not be empty")
        object.__setattr__(self, "source", normalized_source)
        object.__setattr__(self, "source_item_id", normalized_item)
        object.__setattr__(
            self,
            "event_ids",
            normalize_source_event_ids(self.event_ids),
        )


@dataclass(frozen=True, slots=True)
class SourceForgetGateResult:
    """Owner decisions for one page without changing unhandled source semantics."""

    claims: tuple[SourceForgetClaim, ...] = ()
    exact_only_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exact_only_event_ids",
            normalize_source_event_ids(self.exact_only_event_ids),
        )


class SourceForgetOwner(Protocol):
    """Source-domain contract used by the durable forget runner."""

    async def gate(
        self,
        batch: SourceForgetBatch,
    ) -> SourceForgetGateResult: ...

    async def finalize(
        self,
        claims: tuple[SourceForgetClaim, ...],
    ) -> None: ...


class SourceForgetOwnerRegistry:
    """Route exact source identities without scanning unrelated domains."""

    def __init__(self, *, required_sources: tuple[str, ...] = ()) -> None:
        self._owners: dict[str, SourceForgetOwner] = {}
        self._required_sources = {
            str(source or "").strip() for source in required_sources if str(source or "").strip()
        }

    def register(self, source: str, owner: SourceForgetOwner) -> None:
        normalized = str(source or "").strip()
        if not normalized:
            raise ValueError("Source-forget owner source must not be empty")
        if normalized in self._owners:
            raise ValueError(f"Source-forget owner is already registered: {normalized}")
        self._owners[normalized] = owner

    def unregister(self, source: str) -> None:
        self._owners.pop(str(source or "").strip(), None)

    async def gate(
        self,
        batch: SourceForgetBatch,
    ) -> SourceForgetGateResult:
        identities_by_source: dict[str, list[SourceForgetIdentity]] = {}
        for identity in batch.identities:
            identities_by_source.setdefault(identity.source, []).append(identity)

        claims: list[SourceForgetClaim] = []
        exact_only_event_ids: list[str] = []
        for source, identities in identities_by_source.items():
            owner = self._owners.get(source)
            if owner is None:
                if source in self._required_sources:
                    raise SourceForgetOwnerUnavailableError(
                        f"Required source-forget owner is unavailable: {source}"
                    )
                continue
            result = await owner.gate(
                SourceForgetBatch(
                    operation_id=batch.operation_id,
                    selector_kind=batch.selector_kind,
                    identities=tuple(identities),
                    reason=batch.reason,
                    block_source_item=batch.block_source_item,
                )
            )
            identity_event_ids = {identity.event_id for identity in identities}
            identity_item_ids = {identity.source_item_id for identity in identities}
            if any(
                claim.source != source or claim.source_item_id not in identity_item_ids
                for claim in result.claims
            ):
                raise RuntimeError("Source-forget owner returned a claim outside its source batch")
            if not set(result.exact_only_event_ids).issubset(identity_event_ids):
                raise RuntimeError("Source-forget owner returned an event outside its batch")
            claims.extend(result.claims)
            exact_only_event_ids.extend(result.exact_only_event_ids)
        return SourceForgetGateResult(
            claims=tuple(claims),
            exact_only_event_ids=tuple(exact_only_event_ids),
        )

    async def finalize(
        self,
        claims: tuple[SourceForgetClaim, ...],
    ) -> None:
        claims_by_source: dict[str, list[SourceForgetClaim]] = {}
        for claim in claims:
            claims_by_source.setdefault(claim.source, []).append(claim)
        for source, source_claims in claims_by_source.items():
            owner = self._owners.get(source)
            if owner is None:
                raise SourceForgetOwnerUnavailableError(
                    f"Claimed source-forget owner is unavailable: {source}"
                )
            await owner.finalize(tuple(source_claims))


__all__ = [
    "SourceForgetBatch",
    "SourceForgetClaim",
    "SourceForgetGateResult",
    "SourceForgetIdentity",
    "SourceForgetOwner",
    "SourceForgetOwnerRegistry",
    "SourceForgetOwnerUnavailableError",
]
