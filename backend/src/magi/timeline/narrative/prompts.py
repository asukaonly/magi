"""Diary narrative prompt builders.

The system prompt encodes the voice contract (2nd-person, no internal IDs,
no markdown headers, no numeric metrics, no source-name repetition). The
user prompt assembles concrete period evidence — episodes, time bounds,
optional place hints — for a single LLM call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable


def assign_short_ids(
    episodes: list[dict],
) -> tuple[list[dict], dict[str, str]]:
    """Relabel each episode with a short id (``e1``, ``e2`` …) so the LLM
    can echo it back without hallucinating long UUIDs.

    Long opaque identifiers are a known LLM failure mode — even when told
    to copy verbatim, models routinely invent plausible-looking UUIDs and
    bypass the real ones, which makes 100% of returned slices unmatchable
    against the source episodes. Substituting a 2-char tag fixes this at
    the prompt level instead of relying on copy-paste fidelity.

    Args:
        episodes: List of episode dicts. ``episode_id`` may be a UUID, ULID,
            or anything else — the original value is preserved in the
            returned ``short_to_full`` map.

    Returns:
        Tuple of ``(relabeled_episodes, short_to_full_map)``:
          - ``relabeled_episodes``: shallow copies with ``episode_id`` set to
            the short tag. Input list/dicts are not mutated.
          - ``short_to_full_map``: ``{"e1": "<original-id>", ...}``. Used by
            the caller (DiaryNarrativeLLMClient) to rehydrate slice ids on
            the response side.
    """
    short_to_full: dict[str, str] = {}
    relabeled: list[dict] = []
    for index, ep in enumerate(episodes, start=1):
        short = f"e{index}"
        full = str(ep.get("episode_id") or "").strip()
        if full:
            short_to_full[short] = full
        new_ep = dict(ep)
        new_ep["episode_id"] = short
        relabeled.append(new_ep)
    return relabeled, short_to_full


DIARY_NARRATIVE_SYSTEM_PROMPT = """You are a private timeline editor, not a poetic diary writer.
Given evidence from one period, write a grounded Chinese timeline recap that helps
the user quickly understand what the period was really like.

All prose fields must be in Simplified Chinese, written in second person using "你".
Keep proper nouns, product names, file names, URLs, and quoted evidence in their
original language when that is clearer.

Your period-level essence_prose should answer three questions:
1. What actually happened?
2. What made this period different from an ordinary stretch of time?
3. What user-facing interpretation is supported by the evidence?

Write like a sharp personal editor:
- concrete before beautiful;
- chronological when order matters;
- specific nouns before abstract themes;
- plain, natural sentences before literary atmosphere;
- one honest observation is better than a decorative conclusion.

Each episode may include "事件证据" lines. These are real snippets the user touched
during that period: page titles, messages, terminal commands, window titles, media
items, or location/photo notes. Prefer those concrete snippets over abstract episode
labels, topics, or entities. If the evidence says "sleep agency 论文", mention that
specific thing instead of writing "你做了一些研究工作".

Evidence prefixed with "用户原话：" is user-authored text or mood writing. Treat it
as the strongest signal. You may quote a short phrase from it or build the essence
around it if it explains the period.

Output requirements:
- essence_prose: 1-3 sentences, about 35-90 Chinese characters.
- slice_narrative: one sentence per selected episode.
- slice_sensory_detail: leave empty unless the evidence explicitly contains a
  sensory, weather, place, photo, or user-authored detail worth preserving.
- If the evidence is mostly browser titles or commands, keep the text factual and
  slightly interpretive; do not invent an emotional arc.
- Mention source names only when useful; do not repeat source labels.

Avoid reusable literary cliches and vague connective phrasing, especially:
"穿梭", "数字与现实", "定格", "游离", "画上句号", "信息流中寻找锚点",
"屏幕的光", "咖啡已经凉了", "车流声", "键盘敲击声".

Forbidden:
- Do not invent sensory details.
- Do not mention internal ids, including ep-xxx, UUIDs, hashes, or short ids.
- Do not use markdown headings or formatting markers such as ##, **, or ---.
- Do not include numeric metrics such as focus 62% or stress 0.4.
- Do not copy raw URLs or visit counts directly; digest them into readable meaning.
- Do not claim motives, feelings, or places that are not supported by evidence.

Return strict JSON:
{
  "essence_prose": "...",
  "narrative_style": "diary_2p",
  "slices": [
    {"episode_id": "e1", "slice_narrative": "...", "slice_sensory_detail": ""}
  ]
}

Episode id contract — extremely important:
- Each episode in the user prompt has a short id such as e1, e2, e3, e4.
- Every slices[].episode_id must exactly match one of those short ids.
- Do not invent ids. Do not write UUIDs or hashes. Do not add prefixes or suffixes.
- For each episode in the prompt, write at most one slice. You may omit episodes
  that have too little useful evidence, but you must not write slices for episodes
  absent from the prompt.
"""


def build_diary_narrative_user_prompt(
    *,
    scale: str,
    period_start: float,
    period_end: float,
    episodes: Iterable[dict],
    place_hints: Iterable[str] = (),
    excerpts_by_episode: dict[str, list[str]] | None = None,
) -> str:
    """Build the user prompt that gives the LLM concrete period evidence.

    ``excerpts_by_episode`` maps episode_id → small list of content snippets
    (page titles, message text, window names) drawn from L1 events inside the
    episode's time window. When present for an episode, they appear under
    that episode's bullet block so the LLM can ground its prose in specific
    nouns instead of abstract labels.
    """
    # Local time, not UTC. The LLM uses time-of-day descriptors ("午后",
    # "傍晚") based on the hour it sees, and the user reads the resulting
    # diary in their local clock; using UTC produced an 8-hour drift where
    # episodes at 20:00 CST were narrated as "正午" (because LLM saw 12:00).
    start_label = datetime.fromtimestamp(period_start).strftime("%Y-%m-%d %H:%M")
    end_label = datetime.fromtimestamp(period_end).strftime("%Y-%m-%d %H:%M")
    excerpts_by_episode = excerpts_by_episode or {}

    lines: list[str] = []
    lines.append(f"周期尺度：{scale}（{start_label} ~ {end_label}）")

    places = [p for p in place_hints if p and str(p).strip()]
    if places:
        lines.append("主要地点：" + "、".join(places))

    lines.append("")
    lines.append("Episodes（按时间顺序）：")
    any_episode = False
    for ep in episodes:
        any_episode = True
        ep_id = str(ep.get("episode_id") or "").strip()
        ts = float(ep.get("time_start") or 0.0)
        te = float(ep.get("time_end") or ts)
        t_start = datetime.fromtimestamp(ts).strftime("%H:%M")
        t_end = datetime.fromtimestamp(te).strftime("%H:%M")
        label = str(ep.get("label") or ep.get("user_label") or "").strip()
        topics = ep.get("primary_topic_keys") or []
        entities = ep.get("primary_entity_ids") or []
        bits = [f"id={ep_id}", f"{t_start}–{t_end}"]
        if label:
            bits.append(f"label={label!r}")
        if topics:
            bits.append("topics=" + ",".join(str(t) for t in topics[:5]))
        if entities:
            bits.append("entities=" + ",".join(str(e) for e in entities[:5]))
        lines.append("- " + " · ".join(bits))

        excerpts = excerpts_by_episode.get(ep_id) or []
        for excerpt in excerpts:
            # Two-space indent so excerpts read as a sub-list under the episode.
            lines.append(f"  · 事件证据：{excerpt}")

    if not any_episode:
        lines.append("- （这个时段没有 episode；只给 essence_prose 即可，slices 返回空数组）")

    lines.append("")
    lines.append("请按系统提示中的 JSON schema 返回结果。")
    return "\n".join(lines)
