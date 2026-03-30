"""Reranking helpers for hybrid memory retrieval."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Protocol, Sequence

from ...api.llm_draft import build_adapter_from_provider
from ...config import get_config
from ...llm import LLMProviderBridge
from ...utils.runtime import RuntimePaths
from .answerability import (
    extract_query_phrases,
    extract_query_tokens,
    extract_quoted_spans,
    score_eventness,
    score_generic_guidance_penalty,
    score_temporal_anchor,
)
from .models import RetrievalConfig


DEFAULT_LOCAL_RERANKER_PROVIDER_ID = "local"
DEFAULT_LOCAL_RERANKER_CLI_BINARIES = ("llama-cli",)

ProcessRunner = Callable[..., Awaitable[asyncio.subprocess.Process]]


class RerankerBridge(Protocol):
    """Bridge contract shared by provider-backed and CLI-backed rerankers."""

    async def chat_response(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout_seconds: float,
        event_context: Dict[str, Any] | None = None,
    ) -> Any:
        """Return a response object with a ``content`` attribute."""


@dataclass(slots=True)
class LocalCLIRerankerClient:
    """Minimal bridge wrapper around a local reranker CLI process."""

    cli_path: str
    model_path: Path
    max_context_tokens: int = 2048
    process_runner: ProcessRunner = asyncio.create_subprocess_exec

    async def chat_response(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout_seconds: float,
        event_context: Dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        _ = event_context
        prompt = _build_cli_prompt(system_prompt=system_prompt, messages=messages)
        args = [
            self.cli_path,
            "--model",
            str(self.model_path),
            "--prompt",
            prompt,
            "--ctx-size",
            str(max(256, int(self.max_context_tokens))),
            "--n-predict",
            str(max(16, int(max_tokens))),
            "--temp",
            str(float(temperature)),
            "--no-display-prompt",
        ]
        process = await self.process_runner(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=max(timeout_seconds, 0.1))
        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"llama-cli exited with code {process.returncode}: {stderr_text or 'unknown error'}")
        content = stdout.decode("utf-8", errors="ignore").strip()
        if not content:
            raise RuntimeError("llama-cli returned empty output")
        return SimpleNamespace(content=content)


def build_retrieval_reranker(config: RetrievalConfig) -> "BaseRetrievalReranker":
    """Create the configured reranker backend."""
    if not config.reranker_enabled:
        return NoopRetrievalReranker(config)
    if config.reranker_backend == "noop":
        return NoopRetrievalReranker(config)
    if config.reranker_backend == "llm":
        return LLMRetrievalReranker(config)
    return HeuristicRetrievalReranker(config)


class BaseRetrievalReranker:
    """Base reranker contract."""

    def __init__(self, config: RetrievalConfig) -> None:
        self._config = config

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def _enabled_for_layer(self, layer: str) -> bool:
        return layer in set(self._config.reranker_layers)


class NoopRetrievalReranker(BaseRetrievalReranker):
    """Pass-through reranker that only annotates base retrieval metadata."""

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        _ = query
        identifier_key = _identifier_key_for_layer(layer)
        annotated: List[Dict[str, Any]] = []
        for result in results:
            item_id = str(result.get(identifier_key) or "")
            base_score = float(fused_scores.get(item_id, result.get("retrieval_score", 0.0) or 0.0))
            enriched = dict(result)
            enriched["retrieval_score"] = base_score
            enriched["retrieval_trace"] = {
                "backend": "noop",
                "base_rrf_score": round(base_score, 6),
            }
            enriched["reranker_backend"] = "noop"
            enriched["reranker_score"] = base_score
            annotated.append(enriched)
        return annotated


class HeuristicRetrievalReranker(BaseRetrievalReranker):
    """Rule-based reranker shared across memory layers."""

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        if not results:
            return []
        if not self._enabled_for_layer(layer):
            return await NoopRetrievalReranker(self._config).rerank(
                layer=layer,
                results=results,
                query=query,
                fused_scores=fused_scores,
            )

        top_k = max(1, int(self._config.reranker_top_k))
        rerank_slice = list(results[:top_k])
        remainder = list(results[top_k:])
        scored = [
            self._score_item(layer=layer, item=item, query=query, fused_scores=fused_scores)
            for item in rerank_slice
        ]
        scored.sort(
            key=lambda pair: (
                pair[0],
                _secondary_timestamp(pair[1]),
            ),
            reverse=True,
        )
        reranked = [item for _, item in scored]
        remainder_annotated = await NoopRetrievalReranker(self._config).rerank(
            layer=layer,
            results=remainder,
            query=query,
            fused_scores=fused_scores,
        )
        return reranked + remainder_annotated

    def _score_item(
        self,
        *,
        layer: str,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        if layer == "L1":
            return self._score_l1_item(item=item, query=query, fused_scores=fused_scores)
        if layer == "L3":
            return self._score_l3_item(item=item, query=query, fused_scores=fused_scores)
        if layer == "L4":
            return self._score_l4_item(item=item, query=query, fused_scores=fused_scores)
        return self._score_generic_item(layer=layer, item=item, query=query, fused_scores=fused_scores)

    def _score_l1_item(
        self,
        *,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        query_tokens = extract_query_tokens(query)
        query_phrases = extract_query_phrases(query_tokens)
        quoted_phrases = extract_quoted_spans(query)
        content = str(item.get("content") or "")
        lowered = content.lower()
        content_tokens = set(extract_query_tokens(content))
        matched_tokens = [token for token in query_tokens if token in content_tokens]
        phrase_hits = [phrase for phrase in query_phrases if phrase and phrase in lowered]
        quoted_phrase_hits = [phrase for phrase in quoted_phrases if phrase and phrase in lowered]

        item_id = str(item.get("event_id") or "")
        base_rrf_score = float(fused_scores.get(item_id, 0.0))
        author_type = str(item.get("author_type") or "").strip().lower()
        role_bias = 0.35 if author_type == "user" else (-0.1 if author_type == "assistant" else 0.0)
        token_overlap = (len(matched_tokens) / len(query_tokens)) if query_tokens else 0.0
        phrase_score = min(len(phrase_hits), 3) * 0.25
        quoted_phrase_weight = 0.45 if author_type == "user" else 0.15
        quoted_phrase_score = min(len(quoted_phrase_hits), 2) * quoted_phrase_weight
        fact_density = 0.0
        if re.search(r"\b\d{1,2}[/-]\d{1,2}\b", content) or re.search(r"\b\d{1,2}:\d{2}\b", content):
            fact_density += 0.15
        if re.search(r"\bgps\b", lowered):
            fact_density += 0.1
        eventness_score = score_eventness(content, author_type=author_type)
        temporal_anchor_score = score_temporal_anchor(content)

        verbosity_penalty = 0.0
        if author_type == "assistant" and len(content) > 240:
            verbosity_penalty = min((len(content) - 240) / 600.0, 0.25)
        guidance_penalty = score_generic_guidance_penalty(content, author_type=author_type)

        final_score = (
            base_rrf_score
            + role_bias
            + token_overlap
            + phrase_score
            + quoted_phrase_score
            + fact_density
            + eventness_score
            + temporal_anchor_score
            - verbosity_penalty
            - guidance_penalty
        )
        trace = {
            "backend": "heuristic",
            "base_rrf_score": round(base_rrf_score, 6),
            "role_bias": role_bias,
            "token_overlap": round(token_overlap, 6),
            "phrase_hits": phrase_hits,
            "quoted_phrase_hits": quoted_phrase_hits,
            "fact_density": fact_density,
            "eventness_score": eventness_score,
            "temporal_anchor_score": temporal_anchor_score,
            "verbosity_penalty": round(verbosity_penalty, 6),
            "generic_guidance_penalty": round(guidance_penalty, 6),
            "matched_tokens": matched_tokens,
        }
        enriched = dict(item)
        enriched["retrieval_score"] = final_score
        enriched["retrieval_trace"] = trace
        enriched["reranker_backend"] = "heuristic"
        enriched["reranker_score"] = final_score
        return final_score, enriched

    def _score_l3_item(
        self,
        *,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        text = "\n".join(
            part
            for part in [
                str(item.get("summary_type") or "").strip(),
                str(item.get("summary_category") or "").strip(),
                str(item.get("content") or "").strip(),
            ]
            if part
        )
        return self._score_generic_text_item(
            layer="L3",
            item=item,
            item_id=str(item.get("summary_id") or ""),
            text=text,
            query=query,
            fused_scores=fused_scores,
        )

    def _score_l4_item(
        self,
        *,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        text = "\n".join(
            part
            for part in [
                str(item.get("skill_name") or "").strip(),
                str(item.get("skill_category") or "").strip(),
                str(item.get("optimized_prompt") or "").strip(),
            ]
            if part
        )
        return self._score_generic_text_item(
            layer="L4",
            item=item,
            item_id=str(item.get("skill_id") or ""),
            text=text,
            query=query,
            fused_scores=fused_scores,
        )

    def _score_generic_item(
        self,
        *,
        layer: str,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        item_id = str(item.get(_identifier_key_for_layer(layer)) or "")
        text = str(item.get("content") or "")
        return self._score_generic_text_item(
            layer=layer,
            item=item,
            item_id=item_id,
            text=text,
            query=query,
            fused_scores=fused_scores,
        )

    def _score_generic_text_item(
        self,
        *,
        layer: str,
        item: Dict[str, Any],
        item_id: str,
        text: str,
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        query_tokens = extract_query_tokens(query)
        query_phrases = extract_query_phrases(query_tokens)
        lowered = text.lower()
        content_tokens = set(extract_query_tokens(text))
        matched_tokens = [token for token in query_tokens if token in content_tokens]
        phrase_hits = [phrase for phrase in query_phrases if phrase and phrase in lowered]
        matched_chunks = item.get("matched_chunks") if isinstance(item.get("matched_chunks"), list) else []
        best_distance = _best_distance(item, matched_chunks)
        token_overlap = (len(matched_tokens) / len(query_tokens)) if query_tokens else 0.0
        phrase_score = min(len(phrase_hits), 3) * 0.22
        chunk_bonus = min(len(matched_chunks), 3) * 0.08
        distance_bonus = max(0.0, 0.3 - best_distance) if best_distance is not None else 0.0
        generic_penalty = 0.0
        if "general" in lowered or "broad advice" in lowered:
            generic_penalty += 0.12

        base_rrf_score = float(fused_scores.get(item_id, 0.0))
        final_score = (
            base_rrf_score
            + token_overlap
            + phrase_score
            + chunk_bonus
            + distance_bonus
            - generic_penalty
        )
        trace = {
            "backend": "heuristic",
            "layer": layer,
            "base_rrf_score": round(base_rrf_score, 6),
            "token_overlap": round(token_overlap, 6),
            "phrase_hits": phrase_hits,
            "matched_tokens": matched_tokens,
            "chunk_bonus": round(chunk_bonus, 6),
            "best_distance": best_distance,
            "distance_bonus": round(distance_bonus, 6),
            "generic_penalty": round(generic_penalty, 6),
        }
        enriched = dict(item)
        enriched["retrieval_score"] = final_score
        enriched["retrieval_trace"] = trace
        enriched["reranker_backend"] = "heuristic"
        enriched["reranker_score"] = final_score
        return final_score, enriched


class LLMRetrievalReranker(BaseRetrievalReranker):
    """LLM-assisted reranker that refines heuristic ordering for top candidates."""

    def __init__(
        self,
        config: RetrievalConfig,
        *,
        bridge_builder: Callable[[RetrievalConfig], RerankerBridge | None] | None = None,
    ) -> None:
        super().__init__(config)
        self._fallback = HeuristicRetrievalReranker(config)
        self._bridge_builder = bridge_builder or _build_runtime_reranker_bridge
        self._bridge_cache_key: tuple[Any, ...] | None = None
        self._bridge_cache_value: RerankerBridge | None = None

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        base_results = await self._fallback.rerank(
            layer=layer,
            results=results,
            query=query,
            fused_scores=fused_scores,
        )
        if not base_results or not self._enabled_for_layer(layer):
            return base_results

        bridge = self._resolve_bridge()
        if bridge is None:
            return _annotate_llm_fallback(base_results, reason="bridge_unavailable")

        top_k = max(1, int(self._config.reranker_top_k))
        rerank_slice = list(base_results[:top_k])
        remainder = list(base_results[top_k:])
        llm_results = await asyncio.gather(
            *[
                self._score_item_with_llm(
                    bridge=bridge,
                    layer=layer,
                    item=item,
                    query=query,
                )
                for item in rerank_slice
            ],
            return_exceptions=True,
        )

        rescored: list[tuple[float, Dict[str, Any]]] = []
        for item, llm_result in zip(rerank_slice, llm_results):
            if isinstance(llm_result, Exception):
                rescored.append(
                    (
                        float(item.get("retrieval_score", 0.0) or 0.0),
                        _annotate_llm_item_fallback(item, reason=str(llm_result)),
                    )
                )
                continue
            rescored.append(llm_result)

        rescored.sort(
            key=lambda pair: (
                pair[0],
                _secondary_timestamp(pair[1]),
            ),
            reverse=True,
        )
        reranked = [item for _, item in rescored]
        return reranked + remainder

    def _resolve_bridge(self) -> RerankerBridge | None:
        cache_key = (
            self._config.reranker_mode,
            self._config.reranker_remote_provider_id,
            self._config.reranker_remote_model,
            self._config.reranker_local_model_source,
            self._config.reranker_local_managed_model_id,
            self._config.reranker_local_model_file_path,
        )
        if cache_key != self._bridge_cache_key:
            self._bridge_cache_value = self._bridge_builder(self._config)
            self._bridge_cache_key = cache_key
        return self._bridge_cache_value

    async def _score_item_with_llm(
        self,
        *,
        bridge: RerankerBridge,
        layer: str,
        item: Dict[str, Any],
        query: str,
    ) -> tuple[float, Dict[str, Any]]:
        base_score = float(item.get("retrieval_score", 0.0) or 0.0)
        candidate_text = _candidate_text_for_item(
            layer=layer,
            item=item,
            max_chars=self._config.reranker_candidate_max_chars,
        )
        prompt = (
            "Score how well this memory candidate answers the query.\n"
            "Return JSON only with a numeric score between 0 and 1.\n\n"
            f"Layer: {layer}\n"
            f"Query: {query}\n\n"
            f"Candidate:\n{candidate_text}\n"
        )
        response = await bridge.chat_response(
            system_prompt=(
                "You are a retrieval reranker. "
                "Return strict JSON in the form {\"score\": 0.0}. "
                "The score must reflect answer relevance only."
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0.0,
            json_mode=True,
            timeout_seconds=self._config.reranker_timeout_seconds,
            event_context={
                "request_kind": "memory_reranker",
                "layer": layer,
                "provider_mode": self._config.reranker_mode,
            },
        )
        payload = json.loads(str(response.content or "{}"))
        llm_score = max(0.0, min(1.0, float(payload.get("score", 0.0) or 0.0)))
        llm_weight = max(0.0, min(1.0, float(self._config.reranker_llm_weight)))
        final_score = (base_score * (1.0 - llm_weight)) + (llm_score * llm_weight)
        trace = dict(item.get("retrieval_trace") or {})
        prior_backend = str(trace.get("backend") or "heuristic")
        trace.update(
            {
                "backend": "llm",
                "base_backend": prior_backend,
                "base_retrieval_score": round(base_score, 6),
                "llm_score": round(llm_score, 6),
                "reranker_mode": self._config.reranker_mode,
            }
        )
        enriched = dict(item)
        enriched["retrieval_score"] = final_score
        enriched["retrieval_trace"] = trace
        enriched["reranker_backend"] = "llm"
        enriched["reranker_score"] = llm_score
        return final_score, enriched


def _identifier_key_for_layer(layer: str) -> str:
    if layer == "L1":
        return "event_id"
    if layer == "L3":
        return "summary_id"
    if layer == "L4":
        return "skill_id"
    return "id"


def _secondary_timestamp(item: Dict[str, Any]) -> float:
    for key in ("timestamp", "updated_at", "created_at", "period_end"):
        value = item.get(key)
        if value is not None:
            return float(value)
    return 0.0


def _best_distance(item: Dict[str, Any], matched_chunks: List[Dict[str, Any]]) -> float | None:
    if item.get("distance") is not None:
        return float(item["distance"])
    if matched_chunks:
        distance = matched_chunks[0].get("distance")
        if distance is not None:
            return float(distance)
    return None


def _build_runtime_reranker_bridge(config: RetrievalConfig) -> RerankerBridge | None:
    if config.reranker_mode == "remote":
        return _build_provider_reranker_bridge(
            provider_id=str(config.reranker_remote_provider_id or "").strip(),
            model_name=str(config.reranker_remote_model or "").strip(),
        )

    local_provider_bridge = _build_provider_reranker_bridge(
        provider_id=DEFAULT_LOCAL_RERANKER_PROVIDER_ID,
        model_name=_local_provider_model_name(config),
    )
    if local_provider_bridge is not None:
        return local_provider_bridge
    return build_local_cli_reranker_client(config)


def _build_provider_reranker_bridge(*, provider_id: str, model_name: str) -> LLMProviderBridge | None:
    if not provider_id or not model_name:
        return None

    runtime_config = get_config()
    provider = runtime_config.llm.providers.get(provider_id)
    if provider is None or not provider.enabled:
        return None
    if not str(getattr(provider, "api_key", "") or "").strip():
        return None

    try:
        adapter = build_adapter_from_provider(
            provider,
            model=model_name,
            timeout=runtime_config.llm.timeout,
        )
    except Exception:
        return None
    return LLMProviderBridge(adapter)


def build_local_cli_reranker_client(
    config: RetrievalConfig,
    *,
    runtime_paths: RuntimePaths | Any | None = None,
    cli_path_finder: Callable[[str], str | None] = shutil.which,
    process_runner: ProcessRunner = asyncio.create_subprocess_exec,
) -> LocalCLIRerankerClient | None:
    """Build a local CLI reranker bridge when a model file is configured."""
    model_path = _resolve_local_reranker_model_path(config, runtime_paths=runtime_paths)
    if model_path is None:
        return None

    cli_path: str | None = None
    for candidate in DEFAULT_LOCAL_RERANKER_CLI_BINARIES:
        cli_path = cli_path_finder(candidate)
        if cli_path:
            break
    if not cli_path:
        return None

    return LocalCLIRerankerClient(
        cli_path=cli_path,
        model_path=model_path,
        max_context_tokens=max(512, int(config.reranker_local_max_context_tokens)),
        process_runner=process_runner,
    )


def _resolve_local_reranker_model_path(
    config: RetrievalConfig,
    *,
    runtime_paths: RuntimePaths | Any | None = None,
) -> Path | None:
    source = str(config.reranker_local_model_source or "").strip().lower()
    if source == "managed":
        model_id = str(config.reranker_local_managed_model_id or "").strip()
        if not model_id:
            return None
        paths = runtime_paths or RuntimePaths()
        model_dir = Path(paths.managed_reranker_model_dir(model_id))
        if not model_dir.exists() or not model_dir.is_dir():
            return None
        return _find_managed_reranker_model_file(model_dir)

    model_file_path = str(config.reranker_local_model_file_path or "").strip()
    if not model_file_path:
        return None
    resolved = Path(model_file_path).expanduser()
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _find_managed_reranker_model_file(model_dir: Path) -> Path | None:
    preferred = model_dir / "model.gguf"
    if preferred.exists() and preferred.is_file():
        return preferred
    for candidate in sorted(model_dir.glob("*.gguf")):
        if candidate.is_file():
            return candidate
    return None


def _local_provider_model_name(config: RetrievalConfig) -> str:
    if str(config.reranker_local_model_source or "").strip().lower() == "managed":
        return str(config.reranker_local_managed_model_id or "").strip()
    return str(config.reranker_local_model_file_path or "").strip()


def _candidate_text_for_item(*, layer: str, item: Dict[str, Any], max_chars: int) -> str:
    matched_chunks = item.get("matched_chunks") if isinstance(item.get("matched_chunks"), list) else []
    best_chunk_text = ""
    if matched_chunks:
        best_chunk_text = str(matched_chunks[0].get("chunk_text") or matched_chunks[0].get("text") or "").strip()

    if layer == "L1":
        parts = [
            f"author_type: {item.get('author_type') or ''}",
            f"source: {item.get('source') or ''}",
            f"timestamp: {item.get('timestamp') or ''}",
            best_chunk_text or str(item.get("content") or ""),
        ]
    elif layer == "L3":
        parts = [
            f"summary_type: {item.get('summary_type') or ''}",
            f"summary_category: {item.get('summary_category') or ''}",
            best_chunk_text or str(item.get("content") or ""),
        ]
    elif layer == "L4":
        parts = [
            f"skill_name: {item.get('skill_name') or ''}",
            f"skill_category: {item.get('skill_category') or ''}",
            best_chunk_text or str(item.get("optimized_prompt") or item.get("content") or ""),
        ]
    else:
        parts = [best_chunk_text or str(item.get("content") or "")]

    text = "\n".join(part for part in parts if part and str(part).strip())
    return text[:max_chars]


def _build_cli_prompt(*, system_prompt: str, messages: Sequence[Dict[str, Any]]) -> str:
    parts = [str(system_prompt or "").strip()]
    for message in messages:
        role = str(message.get("role") or "user").strip() or "user"
        content = str(message.get("content") or "").strip()
        if content:
            parts.append(f"{role.upper()}:\n{content}")
    parts.append("ASSISTANT:")
    return "\n\n".join(part for part in parts if part)


def _annotate_llm_fallback(results: List[Dict[str, Any]], *, reason: str) -> List[Dict[str, Any]]:
    annotated: List[Dict[str, Any]] = []
    for item in results:
        annotated.append(_annotate_llm_item_fallback(item, reason=reason))
    return annotated


def _annotate_llm_item_fallback(item: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    enriched = dict(item)
    trace = dict(enriched.get("retrieval_trace") or {})
    trace["llm_fallback_reason"] = reason
    enriched["retrieval_trace"] = trace
    return enriched
