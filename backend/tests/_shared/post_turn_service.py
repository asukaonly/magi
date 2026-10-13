"""Isolate analysis and governance unit tests from the separately tested durable queue."""

from magi.agent.post_turn_understanding import PostTurnUnderstandingService as DurablePostTurnUnderstandingService
from magi.memory.post_turn_contracts import PostTurnBatchLease


class _UnusedOutbox:
    async def cancel_post_turn_outcomes(self, **kwargs):
        return 0

    async def ensure_post_turn_lease(self, lease):
        pass

    async def save_post_turn_analysis(self, lease, analysis):
        pass

    async def settle_post_turn_effect(self, lease, effect):
        pass


class PostTurnUnderstandingService(DurablePostTurnUnderstandingService):
    """Exercise analysis with explicit test admission instead of accepted chat rows."""

    def __init__(self, **kwargs):
        super().__init__(chat_store=_UnusedOutbox(), **kwargs)
        l0 = getattr(self._unified_memory, "l0", None)
        if l0 is not None and not hasattr(l0, "processed_attention_outcomes"):
            async def processed_outcomes(outcome_ids):
                return set()
            l0.processed_attention_outcomes = processed_outcomes
        if self._scheduler is not None:
            self._scheduler._max_batch_attempts = 3

    async def _process_batch(self, batch):
        outcomes = tuple(self._outcomes.get(turn.turn_id) for turn in batch)
        if any(outcome is None for outcome in outcomes):
            return True
        lease = PostTurnBatchLease("unit-batch", "unit-token", tuple(turn.turn_id for turn in batch),
                                   1, None, frozenset(), batch[0].persona_id or "")
        return await self._process_serialized_batch(batch, outcomes, lease=lease)
