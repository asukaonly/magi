"""Entity-link operations over the event repository boundary."""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Tuple, cast

from ..ports import MemoryEventRepository


class _L1EventEntityHostProtocol(Protocol):
    event_repository: MemoryEventRepository

    async def initialize(self) -> None: ...


class L1EventEntityMixin:
    """Maintain and query event/entity co-occurrence links."""

    async def write_event_entities(
        self,
        mappings: List[Tuple[str, str, Optional[str], Optional[float]]],
    ) -> int:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.write_event_entities(mappings)

    async def replace_projected_event_entities(
        self,
        *,
        event_id: str,
        revision: int,
        lease_token: str,
        attempt_count: int,
        clear_generation: int,
        mappings: List[Tuple[str, Optional[str], Optional[float]]],
    ) -> bool:
        """Publish one revision-fenced L2 entity-link projection."""

        return await self.replace_projected_event_entities_batch(
            projections=[
                (
                    event_id,
                    revision,
                    lease_token,
                    attempt_count,
                    clear_generation,
                    mappings,
                )
            ]
        )

    async def replace_projected_event_entities_batch(
        self,
        *,
        projections: List[
            Tuple[
                str,
                int,
                str,
                int,
                int,
                List[Tuple[str, Optional[str], Optional[float]]],
            ]
        ],
    ) -> bool:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.replace_projected_event_entities_batch(projections=projections)

    async def align_entity_link_projection_clear_generation(
        self,
        clear_generation: int,
    ) -> int:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.align_entity_link_projection_clear_generation(clear_generation)

    async def get_entity_event_ids(
        self,
        entity_ids: List[str],
        *,
        limit_per_entity: int = 20,
    ) -> Dict[str, List[str]]:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.get_entity_event_ids(entity_ids, limit_per_entity=limit_per_entity)

    async def get_event_entity_ids(
        self,
        event_ids: List[str],
    ) -> Dict[str, List[str]]:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.get_event_entity_ids(event_ids)

    async def expand_by_entities(
        self,
        seed_event_ids: List[str],
        *,
        limit: int = 30,
        exclude_event_ids: Optional[List[str]] = None,
    ) -> List[str]:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.expand_by_entities(seed_event_ids, limit=limit, exclude_event_ids=exclude_event_ids)

    async def resolve_event_entities(self, event_ids: List[str]) -> List[str]:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.resolve_event_entities(event_ids)

    async def find_events_by_entities(
        self,
        entity_ids: List[str],
        *,
        exclude_event_ids: Optional[List[str]] = None,
        limit: int = 30,
    ) -> List[Tuple[str, int]]:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.find_events_by_entities(entity_ids, exclude_event_ids=exclude_event_ids, limit=limit)

    async def filter_ids_by_user(self, event_ids: List[str], user_id: str) -> List[str]:
        host = cast(_L1EventEntityHostProtocol, self)
        await host.initialize()
        return await host.event_repository.filter_ids_by_user(event_ids, user_id)
