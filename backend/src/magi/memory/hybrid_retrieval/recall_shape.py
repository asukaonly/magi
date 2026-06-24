"""Lightweight recall-shape classification for coverage-sensitive queries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Literal

RecallDomain = Literal["photo", "browser", "music", "unknown"]
RecallOperation = Literal["search", "existence", "count", "enumerate", "aggregate"]
RecallCoverage = Literal["sample", "exhaustive", "unknown"]


@dataclass(frozen=True)
class RecallShape:
    """Question-shape signal used by retrieval, separate from query mode."""

    domain_hint: RecallDomain = "unknown"
    operation: RecallOperation = "search"
    desired_coverage: RecallCoverage = "sample"
    confidence: float = 0.0
    matched_cues: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_PHOTO_CUES = (
    "照片",
    "拍照",
    "图片",
    "相册",
    "影像",
    "photo",
    "photos",
    "picture",
    "pictures",
)
_BROWSER_CUES = (
    "浏览",
    "网页",
    "网站",
    "访问",
    "打开过",
    "看过",
    "chrome",
    "safari",
    "edge",
    "firefox",
    "browser",
    "history",
    "site",
    "website",
    "url",
)
_MUSIC_CUES = (
    "听歌",
    "音乐",
    "网易云",
    "歌曲",
    "歌手",
    "专辑",
    "听过",
    "播放",
    "music",
    "song",
    "artist",
    "album",
    "listened",
)
_COUNT_CUES = (
    "几次",
    "多少次",
    "多少张",
    "几张",
    "一共",
    "总共",
    "总计",
    "合计",
    "how many",
    "count",
)
_ENUMERATE_CUES = (
    "哪些",
    "有哪些",
    "列出",
    "所有",
    "全部",
    "都",
    "list all",
)
_AGGREGATE_CUES = (
    "拍过什么",
    "什么照片",
    "拍了什么",
    "拍到什么",
)
_EXISTENCE_CUES = (
    "有没有",
    "是否",
    "是不是",
    "有拍过",
    "拍过吗",
    "拍了吗",
)
_SAMPLE_CUES = (
    "看看",
    "看一下",
    "发几张",
    "找几张",
    "随便",
    "代表",
)


def classify_recall_shape(query: str) -> RecallShape:
    """Classify the answer shape a memory query asks for.

    This intentionally recognizes problem-shape cues only. It does not parse
    entity names such as places, people, or products.
    """
    text = _normalize_query(query)
    matched: list[str] = []

    domain_hint: RecallDomain = "unknown"
    if _has_any(text, _PHOTO_CUES, matched, "domain:photo"):
        domain_hint = "photo"
    elif _has_any(text, _BROWSER_CUES, matched, "domain:browser"):
        domain_hint = "browser"
    elif _has_any(text, _MUSIC_CUES, matched, "domain:music"):
        domain_hint = "music"

    operation: RecallOperation = "search"
    desired_coverage: RecallCoverage = "sample"
    confidence = 0.35

    if _has_any(text, _COUNT_CUES, matched, "count"):
        operation = "count"
        desired_coverage = "exhaustive"
        confidence = 0.9
    elif _has_any(text, _AGGREGATE_CUES, matched, "aggregate"):
        operation = "aggregate"
        desired_coverage = "exhaustive"
        confidence = 0.85
    elif _has_any(text, _ENUMERATE_CUES, matched, "enumerate"):
        operation = "enumerate"
        desired_coverage = "exhaustive"
        confidence = 0.8
    elif _has_any(text, _EXISTENCE_CUES, matched, "existence"):
        operation = "existence"
        desired_coverage = "sample"
        confidence = 0.75
    elif _has_any(text, _SAMPLE_CUES, matched, "sample"):
        operation = "search"
        desired_coverage = "sample"
        confidence = 0.65

    if domain_hint == "unknown":
        confidence = min(confidence, 0.55)

    return RecallShape(
        domain_hint=domain_hint,
        operation=operation,
        desired_coverage=desired_coverage,
        confidence=confidence,
        matched_cues=matched,
    )


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "").strip().casefold())


def _has_any(text: str, cues: tuple[str, ...], matched: list[str], label: str) -> bool:
    for cue in cues:
        normalized = cue.casefold()
        if normalized in text:
            matched.append(label)
            return True
    return False


__all__ = ["RecallShape", "classify_recall_shape"]
