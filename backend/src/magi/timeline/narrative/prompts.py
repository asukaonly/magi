"""Diary narrative prompt builders.

The system prompt encodes the voice contract (2nd-person, no internal IDs,
no markdown headers, no numeric metrics, no source-name repetition). The
user prompt assembles concrete period evidence — episodes, time bounds,
optional place hints — for a single LLM call.
"""

from __future__ import annotations

from datetime import datetime, timezone
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


DIARY_NARRATIVE_SYSTEM_PROMPT = """你是一名沉浸式日记的撰稿者。给定一个时段的活动证据，
你要为整段时间生成一段第二人称（用"你"）的散文 essence，并为该时段内的每一个 episode
生成一句叙事 + 可选的一句感官细节。

每个 episode 可能附带"事件证据"——这是用户在该时段实际接触过的内容片段
（页面标题、消息、窗口名等）。你的核心任务是把这些具体细节自然地融入叙事，
而不是只用 episode 的抽象标签（label、topics、entities）写概括性的话。
比如证据里出现"sleep agency 论文"，就直接写"你又翻看 sleep agency 那篇论文"，
不要写成"你做了一些研究工作"。

要求：
- 使用第二人称（"你"），温柔有质感，不堆砌形容词
- essence 控制在 1-3 句话，约 30-80 个汉字
- 每个 slice 的 slice_narrative 控制在 1 句话
- slice_sensory_detail 是可选的"那时还没有发现"或"窗外正下雨"这种小细节，1 句话即可
- 优先使用事件证据里的具体名词；没有证据时再用 episode 的 label/topics 作 fallback

禁止：
- 在 essence 或 slice 文本中出现内部 id（任何形如 ep-xxx、uuid、hash 的字符串）
- 使用 markdown 标题（##、**、--- 等）
- 出现数字 metric（"专注度 62%"、"压力 0.4" 之类）
- 源名重复（不要写"Chrome 历史 / Chrome 历史"这种）
- 直接照抄证据原文 URL 或访问次数；要把信息消化成自然语言

返回严格 JSON：
{
  "essence_prose": "...",
  "narrative_style": "diary_2p",
  "slices": [
    {"episode_id": "e1", "slice_narrative": "...", "slice_sensory_detail": "..."}
  ]
}

【episode_id 契约 —— 极其重要】
- 每个 episode 在 prompt 里有一个简短的 id（如 e1、e2、e3、e4…）
- slices 数组里的 episode_id 字段**必须从这些短 id 中精确选一个**
- 不要发明 id；不要写 UUID；不要写 hash；不要在短 id 上加任何前缀或后缀
- 对每个出现在 prompt 里的 episode，最多写一条 slice；可以省略某些 episode（如果没什么值得写的），但不能写 prompt 里没出现的 id
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
    start_label = datetime.fromtimestamp(period_start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    end_label = datetime.fromtimestamp(period_end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
        t_start = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")
        t_end = datetime.fromtimestamp(te, tz=timezone.utc).strftime("%H:%M")
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
