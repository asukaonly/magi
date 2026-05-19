"""Diary narrative prompt builders.

The system prompt encodes the voice contract (2nd-person, no internal IDs,
no markdown headers, no numeric metrics, no source-name repetition). The
user prompt assembles concrete period evidence — episodes, time bounds,
optional place hints — for a single LLM call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


DIARY_NARRATIVE_SYSTEM_PROMPT = """你是一名沉浸式日记的撰稿者。给定一个时段的活动证据，
你要为整段时间生成一段第二人称（用"你"）的散文 essence，并为该时段内的每一个 episode
生成一句叙事 + 可选的一句感官细节。

要求：
- 使用第二人称（"你"），温柔有质感，不堆砌形容词
- essence 控制在 1-3 句话，约 30-80 个汉字
- 每个 slice 的 slice_narrative 控制在 1 句话
- slice_sensory_detail 是可选的"那时还没有发现"或"窗外正下雨"这种小细节，1 句话即可

禁止：
- 在 essence 或 slice 文本中出现内部 id（任何形如 ep-xxx、uuid、hash 的字符串）
- 使用 markdown 标题（##、**、--- 等）
- 出现数字 metric（"专注度 62%"、"压力 0.4" 之类）
- 源名重复（不要写"Chrome 历史 / Chrome 历史"这种）

返回严格 JSON：
{
  "essence_prose": "...",
  "narrative_style": "diary_2p",
  "slices": [
    {"episode_id": "ep-xxx", "slice_narrative": "...", "slice_sensory_detail": "..."}
  ]
}

JSON 顶层结构里允许出现 episode_id（这是机器读取的契约，不是给用户看的文本）。
"""


def build_diary_narrative_user_prompt(
    *,
    scale: str,
    period_start: float,
    period_end: float,
    episodes: Iterable[dict],
    place_hints: Iterable[str] = (),
) -> str:
    """Build the user prompt that gives the LLM concrete period evidence."""
    start_label = datetime.fromtimestamp(period_start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    end_label = datetime.fromtimestamp(period_end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

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

    if not any_episode:
        lines.append("- （这个时段没有 episode；只给 essence_prose 即可，slices 返回空数组）")

    lines.append("")
    lines.append("请按系统提示中的 JSON schema 返回结果。")
    return "\n".join(lines)
