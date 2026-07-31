"""Cross-layer LLM manifest selector for hybrid retrieval results.

After per-layer retrieval + RRF fusion + reranking + result fusion (dedup/budget),
this module performs a final cross-layer LLM ranking to select the most relevant
candidates across all memory layers for a given query.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, List

from magi.utils.diagnostic_logging import full_content_logging_enabled

from .manifest_candidates import (
    ManifestCandidate,
    ManifestCandidates,
    apply_manifest_selection,
    build_manifest_candidates,
)
from .models import RetrievalConfig, RetrievalPayload

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a memory retrieval ranker. Given a user query and numbered memory candidates "
    "from different layers (L1=events, L2=knowledge, L3=reflections, L4=procedures), "
    "select the candidates most relevant to answering the query.\n"
    'Return strict JSON: {"selected": [0, 3, 7, ...]} where values are candidate indices.\n'
    "Order by relevance (most relevant first). Only include candidates that help answer the query."
)


class ManifestSelector:
    """Cross-layer LLM-based manifest selector for retrieval results."""

    def __init__(self, config: RetrievalConfig) -> None:
        self._config = config

    async def select(
        self,
        payload: RetrievalPayload,
        query: str,
        llm_bridge: Any,
    ) -> RetrievalPayload:
        """Rank and prune candidates cross-layer using LLM.

        Args:
            payload: Fused retrieval payload (post-dedup, post-budget).
            query: Original user query.
            llm_bridge: LLM provider bridge with ``chat()`` method.

        Returns:
            Modified payload with candidates reordered/pruned by LLM relevance.
        """
        if llm_bridge is None:
            payload.trace["manifest_selector"] = "skipped_no_bridge"
            return payload

        manifest = build_manifest_candidates(
            payload,
            max_chars=self._config.manifest_selector_candidate_max_chars,
        )
        if not manifest.candidates:
            payload.trace["manifest_selector"] = "skipped_empty"
            return payload

        return await self._select_with_llm(
            payload,
            query=query,
            llm_bridge=llm_bridge,
            manifest=manifest,
        )

    async def _select_with_llm(
        self,
        payload: RetrievalPayload,
        *,
        query: str,
        llm_bridge: Any,
        manifest: ManifestCandidates,
    ) -> RetrievalPayload:
        candidates_for_llm = self._llm_candidates(manifest.candidates)
        user_prompt = self._build_user_prompt(query, candidates_for_llm)

        t0 = time.monotonic()
        try:
            raw = await self._request_selection(llm_bridge, user_prompt)
            elapsed_ms = (time.monotonic() - t0) * 1000
            selected_indices = self._parse_response(
                raw,
                len(candidates_for_llm),
                max_output=self._config.manifest_selector_max_output,
            )
            logger.info(
                "ManifestSelector completed: %d/%d candidates selected, elapsed=%.1fms",
                len(selected_indices),
                len(candidates_for_llm),
                elapsed_ms,
            )
            payload = apply_manifest_selection(
                payload,
                selected_indices,
                manifest.index_map,
            )
            self._record_success_trace(
                payload,
                len(candidates_for_llm),
                selected_indices,
                elapsed_ms,
            )
            return payload
        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "ManifestSelector failed (elapsed=%.1fms), returning original payload",
                elapsed_ms,
                exc_info=True,
            )
            payload.trace["manifest_selector"] = "error_fallback"
            return payload

    def _llm_candidates(self, candidates: List[ManifestCandidate]) -> List[ManifestCandidate]:
        top_k = max(1, self._config.manifest_selector_top_k)
        return candidates[:top_k]

    def _build_user_prompt(
        self,
        query: str,
        candidates_for_llm: List[ManifestCandidate],
    ) -> str:
        prompt_lines = [f"Query: {query}\n\nCandidates:"]
        for idx, (layer, text) in enumerate(candidates_for_llm):
            prompt_lines.append(f"[{idx}] ({layer}) {text}")
        prompt_lines.append(
            f"\nSelect up to {self._config.manifest_selector_max_output} "
            'most relevant candidates. Return JSON: {"selected": [idx, ...]}'
        )
        return "\n".join(prompt_lines)

    async def _request_selection(self, llm_bridge: Any, user_prompt: str) -> Any:
        return await llm_bridge.chat(
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=256,
            temperature=0.0,
            json_mode=True,
            disable_thinking=True,
            timeout_seconds=self._config.manifest_selector_timeout_seconds,
            event_context={
                "request_kind": "memory:hybrid_manifest_selector",
                "agent_id": "memory:hybrid_retrieval",
            },
        )

    @staticmethod
    def _record_success_trace(
        payload: RetrievalPayload,
        input_count: int,
        selected_indices: List[int],
        elapsed_ms: float,
    ) -> None:
        payload.trace["manifest_selector"] = "applied"
        payload.trace["manifest_selector_input_count"] = input_count
        payload.trace["manifest_selector_output_count"] = len(selected_indices)
        payload.trace["manifest_selector_elapsed_ms"] = round(elapsed_ms, 1)

    @staticmethod
    def _parse_response(raw: Any, candidate_count: int, *, max_output: int = 10) -> List[int]:
        """Parse LLM response to extract selected candidate indices."""
        # Fallback: preserve original top-K order when LLM output is unusable.
        fallback = list(range(min(candidate_count, max_output)))

        content = str(getattr(raw, "content", raw) or "{}")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(
                "ManifestSelector: invalid JSON response: %s",
                (
                    content[:200]
                    if full_content_logging_enabled()
                    else f"[content omitted; chars={len(content)}]"
                ),
            )
            return fallback

        selected = data.get("selected")
        if not isinstance(selected, list):
            logger.warning("ManifestSelector: no 'selected' array in response")
            return fallback

        valid: List[int] = []
        seen: set[int] = set()
        for item in selected:
            try:
                idx = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < candidate_count and idx not in seen:
                valid.append(idx)
                seen.add(idx)
        return valid if valid else fallback
