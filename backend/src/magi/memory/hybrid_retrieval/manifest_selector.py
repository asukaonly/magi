"""Cross-layer LLM manifest selector for hybrid retrieval results.

After per-layer retrieval + RRF fusion + reranking + result fusion (dedup/budget),
this module performs a final cross-layer LLM ranking to select the most relevant
candidates across all memory layers for a given query.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Tuple

from .models import RetrievalConfig, RetrievalPayload

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a memory retrieval ranker. Given a user query and numbered memory candidates "
    "from different layers (L1=events, L2=knowledge, L3=reflections, L4=procedures), "
    "select the candidates most relevant to answering the query.\n"
    "Return strict JSON: {\"selected\": [0, 3, 7, ...]} where values are candidate indices.\n"
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

        candidates, index_map = self._build_candidate_list(payload)
        if not candidates:
            payload.trace["manifest_selector"] = "skipped_empty"
            return payload

        top_k = max(1, self._config.manifest_selector_top_k)
        candidates_for_llm = candidates[:top_k]

        prompt_lines = [f"Query: {query}\n\nCandidates:"]
        for idx, (layer, text) in enumerate(candidates_for_llm):
            prompt_lines.append(f"[{idx}] ({layer}) {text}")
        prompt_lines.append(
            f"\nSelect up to {self._config.manifest_selector_max_output} "
            "most relevant candidates. Return JSON: {\"selected\": [idx, ...]}"
        )
        user_prompt = "\n".join(prompt_lines)

        t0 = time.monotonic()
        try:
            raw = await llm_bridge.chat(
                system_prompt=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=256,
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                timeout_seconds=self._config.manifest_selector_timeout_seconds,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            selected_indices = self._parse_response(
                raw, len(candidates_for_llm),
                max_output=self._config.manifest_selector_max_output,
            )
            logger.info(
                "ManifestSelector completed: %d/%d candidates selected, elapsed=%.1fms",
                len(selected_indices), len(candidates_for_llm), elapsed_ms,
            )
            payload = self._apply_selection(payload, selected_indices, index_map)
            payload.trace["manifest_selector"] = "applied"
            payload.trace["manifest_selector_input_count"] = len(candidates_for_llm)
            payload.trace["manifest_selector_output_count"] = len(selected_indices)
            payload.trace["manifest_selector_elapsed_ms"] = round(elapsed_ms, 1)
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

    def _build_candidate_list(
        self,
        payload: RetrievalPayload,
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, int]]]:
        """Build a flat numbered list of candidates across all layers.

        Returns:
            (candidates, index_map) where:
            - candidates: list of (layer_tag, text_snippet)
            - index_map: list of (layer_tag, original_index) for each candidate
        """
        max_chars = max(50, self._config.manifest_selector_candidate_max_chars)
        candidates: List[Tuple[str, str]] = []
        index_map: List[Tuple[str, int]] = []

        for i, ev in enumerate(payload.l1_events):
            text = _truncate(str(ev.get("content") or ""), max_chars)
            ts = ev.get("timestamp") or ""
            snippet = f"[{ts}] {text}" if ts else text
            candidates.append(("L1", snippet))
            index_map.append(("l1_events", i))

        for i, card in enumerate(payload.l2_entity_cards):
            name = card.get("name") or card.get("entity_id") or ""
            etype = card.get("entity_type") or ""
            attrs = card.get("attributes") or {}
            text = _truncate(f"{name} ({etype}): {json.dumps(attrs, ensure_ascii=False)}", max_chars)
            candidates.append(("L2", text))
            index_map.append(("l2_entity_cards", i))

        for i, rel in enumerate(payload.l2_relationships):
            subj = rel.get("subject_name") or rel.get("subject_id") or ""
            pred = rel.get("predicate") or ""
            obj = rel.get("object_name") or rel.get("object_id") or ""
            text = _truncate(f"{subj} --{pred}--> {obj}", max_chars)
            candidates.append(("L2", text))
            index_map.append(("l2_relationships", i))

        for i, assertion in enumerate(payload.l2_assertions):
            entity = assertion.get("entity_name") or assertion.get("entity_id") or ""
            trait = assertion.get("trait_family") or ""
            value = assertion.get("value") or assertion.get("content") or ""
            text = _truncate(f"{entity} [{trait}]: {value}", max_chars)
            candidates.append(("L2", text))
            index_map.append(("l2_assertions", i))

        for i, refl in enumerate(payload.l3_reflections):
            text = _truncate(str(refl.get("content") or refl.get("summary") or ""), max_chars)
            period = refl.get("period") or ""
            snippet = f"[{period}] {text}" if period else text
            candidates.append(("L3", snippet))
            index_map.append(("l3_reflections", i))

        for i, proc in enumerate(payload.l4_procedures):
            text = _truncate(str(proc.get("optimized_prompt") or proc.get("content") or ""), max_chars)
            candidates.append(("L4", text))
            index_map.append(("l4_procedures", i))

        return candidates, index_map

    @staticmethod
    def _parse_response(raw: Any, candidate_count: int, *, max_output: int = 10) -> List[int]:
        """Parse LLM response to extract selected candidate indices."""
        # Fallback: preserve original top-K order when LLM output is unusable.
        fallback = list(range(min(candidate_count, max_output)))

        content = str(getattr(raw, "content", raw) or "{}")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("ManifestSelector: invalid JSON response: %s", content[:200])
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

    @staticmethod
    def _apply_selection(
        payload: RetrievalPayload,
        selected_indices: List[int],
        index_map: List[Tuple[str, int]],
    ) -> RetrievalPayload:
        """Rebuild payload keeping only selected candidates in LLM-ranked order."""
        selected_by_field: Dict[str, List[int]] = {}
        for global_idx in selected_indices:
            if global_idx >= len(index_map):
                continue
            field_name, original_idx = index_map[global_idx]
            selected_by_field.setdefault(field_name, []).append(original_idx)

        field_to_attr = {
            "l1_events": "l1_events",
            "l2_entity_cards": "l2_entity_cards",
            "l2_relationships": "l2_relationships",
            "l2_assertions": "l2_assertions",
            "l3_reflections": "l3_reflections",
            "l4_procedures": "l4_procedures",
        }

        for field_name, attr_name in field_to_attr.items():
            original = getattr(payload, attr_name)
            if field_name in selected_by_field:
                ordered_indices = selected_by_field[field_name]
                setattr(
                    payload,
                    attr_name,
                    [original[i] for i in ordered_indices if i < len(original)],
                )
            else:
                setattr(payload, attr_name, [])

        return payload


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars with ellipsis."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."
