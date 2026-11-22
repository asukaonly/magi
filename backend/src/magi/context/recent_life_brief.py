"""Zero-LLM ambient recent life brief builder for chat prompt context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import re
import time
from typing import Any

from ..core.logger import get_logger
from ..core.sqlite import sqlite_connection_async
from ..memory.evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from ..memory.l2.corrections.repository import (
    MemoryCorrectionRepository,
    get_subject_revision_generation,
)
from ..memory.privacy_filter import (
    is_active_chat_llm_local,
    redact_cloud_egress_text,
    resolve_privacy_filter_settings,
    should_exclude_event_from_llm,
)
from ..memory.source_event_governance import source_event_derivation_block_ids

logger = get_logger(__name__)

RECENT_LIFE_BRIEF_WINDOW_SECONDS = 72 * 3600
RECENT_LIFE_CUE_WINDOW_SECONDS = 24 * 3600
RECENT_LIFE_BRIEF_DEFAULT_TTL_SECONDS = 300.0
RECENT_LIFE_BRIEF_MAX_TOKENS = 350

RECENT_LIFE_BRIEF_HEADER_LINES: tuple[str, ...] = (
    "# Recent Authorized Activity (Background Only)",
    "[System Notice: Concise summary of the user's recent authorized activity (last 72h). "
    "Echo lightly only when naturally relevant to the conversation. Never recite it like a "
    "surveillance log, and never claim details beyond the listed items.]",
)

_EXCLUDED_SOURCES = frozenset({"chat", "system", "runtime"})
_EXCLUDED_DOMAINS = frozenset({"runtime_telemetry", "system_control"})
_MANUAL_SOURCES = frozenset({"manual", "manual_entry", "journal", "mood"})
_MANUAL_EVENT_TYPES = frozenset({"manual_entry", "mood_entry", "journal_entry"})

_SOURCE_PRIORITY: dict[str, int] = {
    "manual": 0,
    "manual_entry": 0,
    "journal": 0,
    "mood": 0,
    "netease_music": 1,
    "system_media": 1,
    "music": 1,
    "git_activity": 2,
    "git": 2,
    "calendar": 3,
    "chrome_history": 4,
    "chrome": 4,
    "browser": 4,
    "photo_library": 5,
    "photos": 5,
    "screen_time": 6,
    "terminal_history": 7,
}

_SOURCE_LABELS: dict[str, str] = {
    "manual": "Note",
    "manual_entry": "Note",
    "journal": "Note",
    "mood": "Mood note",
    "netease_music": "Music",
    "system_media": "Media",
    "music": "Music",
    "git_activity": "Git",
    "git": "Git",
    "calendar": "Calendar",
    "chrome_history": "Browsing",
    "chrome": "Browsing",
    "browser": "Browsing",
    "photo_library": "Photos",
    "photos": "Photos",
    "screen_time": "Apps",
    "terminal_history": "Terminal",
}

_LOW_MOOD_VALUES = frozenset({
    "low",
    "sad",
    "down",
    "tired",
    "exhausted",
    "anxious",
    "stressed",
    "overwhelmed",
    "bad",
    "depressed",
})
_LOW_MOOD_CUE_TERMS: tuple[str, ...] = (
    "低落",
    "难过",
    "沮丧",
    "好累",
    "累死",
    "疲惫",
    "失眠",
    "焦虑",
    "压力大",
    "崩溃",
    "撑不住",
    "心累",
    "exhausted",
    "burned out",
    "burnt out",
    "overwhelmed",
    "stressed",
    "anxious",
    "feeling down",
    "rough day",
)

_CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")
_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s*")


def estimate_brief_tokens(text: str) -> int:
    """Conservatively estimate LLM tokens for mixed CJK/Latin text."""
    if not text:
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    non_cjk_len = max(0, len(text) - cjk_count)
    return cjk_count + math.ceil(non_cjk_len / 3.5)


def _clean_single_line(text: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(text or "")).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = _clean_single_line(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max(1, max_chars - 1)].rstrip()}…"


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _is_excluded_from_llm(metadata: dict[str, Any]) -> bool:
    if bool(metadata.get("exclude_from_llm")):
        return True
    if str(metadata.get("privacy_level") or "").strip().lower() == "private":
        return True
    privacy = metadata.get("privacy")
    if isinstance(privacy, dict) and bool(privacy.get("exclude_from_llm")):
        return True
    return False


def _extract_event_highlight(event: dict[str, Any], metadata: dict[str, Any]) -> str:
    """Build a short single-line highlight from event metadata or content."""
    timeline = metadata.get("timeline")
    timeline_dict = timeline if isinstance(timeline, dict) else {}

    track = _clean_single_line(metadata.get("track_title") or metadata.get("song_name"))
    artist = _clean_single_line(metadata.get("artist") or metadata.get("artist_name"))
    if track and artist:
        return _truncate_text(f"{track} - {artist}", 68)
    if track:
        return _truncate_text(track, 68)

    repo = _clean_single_line(metadata.get("repo") or metadata.get("repository"))
    commit_msg = _clean_single_line(
        metadata.get("commit_message") or metadata.get("subject")
    )
    if repo and commit_msg:
        return _truncate_text(f"{repo}: {commit_msg}", 68)

    title = _clean_single_line(
        timeline_dict.get("title")
        or metadata.get("title")
        or metadata.get("page_title")
        or metadata.get("summary")
    )
    domain = _clean_single_line(metadata.get("domain") or metadata.get("host"))
    if title and domain and domain.lower() not in title.lower():
        return _truncate_text(f"{title} ({domain})", 68)
    if title:
        return _truncate_text(title, 68)

    content = _clean_single_line(event.get("content"))
    return _truncate_text(content, 72)


def _format_source_label(source: str) -> str:
    normalized = source.strip().lower()
    if normalized in _SOURCE_LABELS:
        return _SOURCE_LABELS[normalized]
    return normalized.replace("_", " ").replace("-", " ").title() or "Activity"


def _first_sentence(text: str, max_chars: int = 105) -> str:
    cleaned = _clean_single_line(text)
    if not cleaned:
        return ""
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]
    first = parts[0] if parts else cleaned
    return _truncate_text(first, max_chars)


def _extract_recent_user_context_cue(
    events: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    now: float,
) -> str | None:
    """Return a restrained, read-only 24h context cue when strongly warranted."""
    cutoff = now - RECENT_LIFE_CUE_WINDOW_SECONDS
    late_night_timestamps: list[float] = []

    for event, metadata in events:
        ts = float(event.get("timestamp") or 0.0)
        if ts < cutoff or ts > now + 60.0:
            continue
        source = str(event.get("source") or "").strip().lower()
        event_type = str(event.get("event_type") or "").strip().lower()

        if source in _MANUAL_SOURCES or event_type in _MANUAL_EVENT_TYPES:
            mood_val = str(
                metadata.get("mood")
                or metadata.get("mood_label")
                or metadata.get("emotion")
                or ""
            ).strip().lower()
            content_lower = _clean_single_line(event.get("content")).lower()
            if mood_val in _LOW_MOOD_VALUES or any(
                term in content_lower for term in _LOW_MOOD_CUE_TERMS
            ):
                return (
                    "User logged a personal note mentioning low energy, stress, "
                    "or low mood within the last 24h."
                )

        local_hour = datetime.fromtimestamp(ts).hour
        if 0 <= local_hour < 5:
            late_night_timestamps.append(ts)

    if len(late_night_timestamps) >= 3:
        late_night_timestamps.sort()
        span_seconds = late_night_timestamps[-1] - late_night_timestamps[0]
        if span_seconds >= 20 * 60 or len(late_night_timestamps) >= 4:
            return (
                "User had sustained late-night activity between 00:00 and 05:00 "
                "within the last 24h."
            )

    return None


@dataclass(frozen=True, slots=True)
class RecentLifeBrief:
    """Compact, deterministic recent activity summary for prompt injection."""

    entries: tuple[str, ...] = ()
    recent_user_context_cue: str | None = None
    estimated_tokens: int = 0
    source_count: int = 0
    excluded_local_only_count: int = 0
    redacted: bool = False


@dataclass(slots=True)
class _CacheEntry:
    token: tuple[int, int, int, int]
    created_at: float
    brief: RecentLifeBrief


class RecentLifeBriefService:
    """Builds a zero-LLM <=350-token summary of the user's last 72h activity."""

    def __init__(
        self,
        unified_memory: Any,
        *,
        ttl_seconds: float = RECENT_LIFE_BRIEF_DEFAULT_TTL_SECONDS,
        window_seconds: float = RECENT_LIFE_BRIEF_WINDOW_SECONDS,
        max_tokens: int = RECENT_LIFE_BRIEF_MAX_TOKENS,
    ) -> None:
        self._memory = unified_memory
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._window_seconds = max(3600.0, float(window_seconds))
        self._max_tokens = max(80, int(max_tokens))
        self._cache: dict[tuple[str, bool], _CacheEntry] = {}

    def invalidate(self, user_id: str | None = None) -> None:
        """Clear cached briefs for one user or all users."""
        if user_id is None:
            self._cache.clear()
        else:
            self._cache.pop((user_id, False), None)
            self._cache.pop((user_id, True), None)

    def _invalidation_token(self) -> tuple[int, int, int, int]:
        if self._memory is None:
            return (0, 0, 0, 0)
        epoch_fn = getattr(self._memory, "memory_operation_epoch", None)
        epoch = int(epoch_fn()) if callable(epoch_fn) else 0
        l1_ver = int(getattr(getattr(self._memory, "l1", None), "mutation_version", 0) or 0)
        l3_ver = int(getattr(getattr(self._memory, "l3", None), "mutation_version", 0) or 0)
        rev_gen = get_subject_revision_generation()
        return (epoch, l1_ver, l3_ver, rev_gen)

    async def build_brief(
        self,
        *,
        user_id: str,
        now: float | None = None,
        is_local_provider: bool | None = None,
    ) -> RecentLifeBrief:
        """Return cached or freshly built 72h brief with zero LLM calls."""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id or self._memory is None:
            return RecentLifeBrief()
        l1 = getattr(self._memory, "l1", None)
        if l1 is None:
            return RecentLifeBrief()

        effective_local = (
            bool(is_local_provider)
            if is_local_provider is not None
            else is_active_chat_llm_local()
        )
        current_time = float(now if now is not None else time.time())
        token = self._invalidation_token()
        cache_key = (normalized_user_id, effective_local)
        cached = self._cache.get(cache_key)
        if (
            cached is not None
            and cached.token == token
            and (current_time - cached.created_at) < self._ttl_seconds
            and current_time >= cached.created_at
        ):
            return cached.brief

        brief = await self._compute_brief(
            user_id=normalized_user_id,
            now=current_time,
            is_local_provider=effective_local,
        )
        # Re-read token so concurrent mutations during read don't poison cache.
        post_token = self._invalidation_token()
        if post_token == token:
            self._cache[cache_key] = _CacheEntry(
                token=post_token,
                created_at=current_time,
                brief=brief,
            )
        return brief

    async def _compute_brief(
        self,
        *,
        user_id: str,
        now: float,
        is_local_provider: bool,
    ) -> RecentLifeBrief:
        start_time = now - self._window_seconds
        l1 = getattr(self._memory, "l1", None)
        if l1 is None:
            return RecentLifeBrief()

        raw_events = await l1.query_events(
            user_id=user_id,
            start_time=start_time,
            end_time=now,
            l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES),
            limit=80,
            include_metadata_json=True,
            include_embedding_fields=False,
            order_by="timestamp_desc",
        )
        events, excluded_local_only_count = await self._filter_governed_events(
            raw_events,
            is_local_provider=is_local_provider,
        )

        day_summaries = await self._fetch_recent_day_summaries(
            start_time=start_time,
            end_time=now,
        )

        candidate_lines: list[str] = []
        for summary in day_summaries[:2]:
            summary_id = str(summary.get("summary_id") or "").strip()
            snippet = _first_sentence(
                str(summary.get("essence_prose") or summary.get("content") or "")
            )
            if not summary_id or not snippet:
                continue
            period_ts = float(
                summary.get("period_start")
                or summary.get("period_end")
                or summary.get("updated_at")
                or now
            )
            date_label = datetime.fromtimestamp(period_ts).strftime("%m-%d")
            candidate_lines.append(
                f"- Day summary ({date_label}): {snippet} [l3 | {summary_id}]"
            )

        grouped_sources = self._group_events_by_source(events)
        for source, items in grouped_sources[:6]:
            line = self._format_source_line(source, items)
            if line:
                candidate_lines.append(line)

        privacy_cfg = resolve_privacy_filter_settings()
        should_redact = (not is_local_provider) and privacy_cfg.enabled and privacy_cfg.redact_cloud_egress
        any_redacted = False
        if should_redact and candidate_lines:
            redacted_lines: list[str] = []
            for line in candidate_lines:
                clean_line, changed = redact_cloud_egress_text(line)
                any_redacted = any_redacted or changed
                redacted_lines.append(clean_line)
            candidate_lines = redacted_lines

        cue = _extract_recent_user_context_cue(events, now=now)
        if should_redact and cue:
            cue, cue_changed = redact_cloud_egress_text(cue)
            any_redacted = any_redacted or cue_changed

        if not candidate_lines:
            return RecentLifeBrief(
                entries=(),
                recent_user_context_cue=cue,
                estimated_tokens=0,
                source_count=0,
                excluded_local_only_count=excluded_local_only_count,
                redacted=any_redacted,
            )

        header_text = "\n".join(RECENT_LIFE_BRIEF_HEADER_LINES) + "\n"
        header_tokens = estimate_brief_tokens(header_text)
        remaining_budget = max(24, self._max_tokens - header_tokens)

        selected: list[str] = []
        used_tokens = header_tokens
        for line in candidate_lines:
            line_tokens = estimate_brief_tokens(line + "\n")
            if used_tokens + line_tokens <= self._max_tokens:
                selected.append(line)
                used_tokens += line_tokens
            elif not selected:
                # Guarantee at least one entry fits strictly under the token cap.
                clipped = self._clip_line_to_tokens(line, remaining_budget)
                if clipped:
                    selected.append(clipped)
                    used_tokens = header_tokens + estimate_brief_tokens(clipped + "\n")
                break

        return RecentLifeBrief(
            entries=tuple(selected),
            recent_user_context_cue=cue,
            estimated_tokens=used_tokens if selected else 0,
            source_count=len(grouped_sources),
            excluded_local_only_count=excluded_local_only_count,
            redacted=any_redacted,
        )

    async def _filter_governed_events(
        self,
        raw_events: list[dict[str, Any]],
        *,
        is_local_provider: bool,
    ) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], int]:
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        excluded_local_only_count = 0
        for event in raw_events or []:
            if not isinstance(event, dict):
                continue
            if event.get("deleted_at") is not None:
                continue
            source = str(event.get("source") or "").strip().lower()
            domain = str(event.get("memory_domain") or "").strip().lower()
            if not source or source in _EXCLUDED_SOURCES or domain in _EXCLUDED_DOMAINS:
                continue
            metadata = _parse_metadata(event.get("metadata_json"))
            if should_exclude_event_from_llm(
                {**event, "metadata_json": metadata},
                is_local_provider=is_local_provider,
            ):
                excluded_local_only_count += 1
                continue
            content = _clean_single_line(event.get("content"))
            if not content and not metadata:
                continue
            candidates.append((event, metadata))

        if not candidates:
            return [], excluded_local_only_count

        memory_db_path = getattr(self._memory, "memory_db_path", None)
        if not memory_db_path:
            return candidates, excluded_local_only_count

        event_ids = [
            str(event.get("event_id") or "").strip()
            for event, _ in candidates
            if str(event.get("event_id") or "").strip()
        ]
        if not event_ids:
            return [], excluded_local_only_count

        blocked: set[str] = set()
        try:
            async with sqlite_connection_async(memory_db_path) as db:
                blocked.update(await source_event_derivation_block_ids(db, event_ids))
            correction_repo = MemoryCorrectionRepository(memory_db_path)
            blocked.update(
                await correction_repo.active_correction_evidence_event_ids(event_ids)
            )
        except Exception as exc:
            logger.debug(
                "RecentLifeBrief governance check skipped due to unavailable schema",
                error=str(exc),
            )
            return candidates, excluded_local_only_count

        return (
            [
                (event, metadata)
                for event, metadata in candidates
                if str(event.get("event_id") or "").strip() not in blocked
            ],
            excluded_local_only_count,
        )

    async def _fetch_recent_day_summaries(
        self,
        *,
        start_time: float,
        end_time: float,
    ) -> list[dict[str, Any]]:
        l3 = getattr(self._memory, "l3", None)
        if l3 is None or not hasattr(l3, "list_summaries"):
            return []
        try:
            rows = await l3.list_summaries(
                summary_type="temporal",
                summary_category="day",
                start_time=start_time,
                end_time=end_time,
                limit=2,
            )
        except Exception as exc:
            logger.debug("RecentLifeBrief L3 summary fetch failed", error=str(exc))
            return []
        return [row for row in (rows or []) if isinstance(row, dict)]

    @staticmethod
    def _group_events_by_source(
        events: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> list[tuple[str, list[tuple[dict[str, Any], dict[str, Any]]]]]:
        grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for event, metadata in events:
            source = str(event.get("source") or "").strip().lower()
            grouped.setdefault(source, []).append((event, metadata))

        def _sort_key(
            pair: tuple[str, list[tuple[dict[str, Any], dict[str, Any]]]],
        ) -> tuple[int, float]:
            src, items = pair
            priority = _SOURCE_PRIORITY.get(src, 50)
            newest_ts = max(float(ev.get("timestamp") or 0.0) for ev, _ in items)
            return (priority, -newest_ts)

        return sorted(grouped.items(), key=_sort_key)

    @staticmethod
    def _format_source_line(
        source: str,
        items: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> str:
        highlights: list[str] = []
        seen_lower: set[str] = set()
        primary_event_id = ""
        for event, metadata in items:
            event_id = str(event.get("event_id") or "").strip()
            if not primary_event_id and event_id:
                primary_event_id = event_id
            highlight = _extract_event_highlight(event, metadata)
            if not highlight:
                continue
            key = highlight.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            highlights.append(highlight)
            if len(highlights) >= 2:
                break

        if not highlights or not primary_event_id:
            return ""

        label = _format_source_label(source)
        count = len(items)
        body = "; ".join(highlights)
        prefix = f"- {label} ({count}): " if count > 1 else f"- {label}: "
        suffix = f" [{source} | {primary_event_id}]"
        max_body_chars = max(24, 140 - len(prefix) - len(suffix))
        return f"{prefix}{_truncate_text(body, max_body_chars)}{suffix}"

    @staticmethod
    def _clip_line_to_tokens(line: str, max_tokens: int) -> str:
        if estimate_brief_tokens(line) <= max_tokens:
            return line
        bracket_idx = line.rfind(" [")
        suffix = line[bracket_idx:] if bracket_idx != -1 else ""
        body = line[:bracket_idx] if bracket_idx != -1 else line
        while body and estimate_brief_tokens(f"{body}…{suffix}") > max_tokens:
            body = body[:-4].rstrip()
        if not body:
            return ""
        return f"{body}…{suffix}"


__all__ = [
    "RECENT_LIFE_BRIEF_HEADER_LINES",
    "RECENT_LIFE_BRIEF_MAX_TOKENS",
    "RecentLifeBrief",
    "RecentLifeBriefService",
    "estimate_brief_tokens",
]
