"""Anchor and text-token helpers for L2 experience seed discovery."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

from .seed_models import _EpisodeSeedFeatures


GENERIC_EXPERIENCE_ANCHORS = {
    "browser",
    "chrome",
    "gmail",
    "google",
    "google search",
    "github",
    "local user",
    "local_user",
    "self",
    "software:chrome",
    "software:gmail",
    "software:google",
    "software:github",
    "twitter",
    "user",
    "user local user",
    "user self",
    "user:local_user",
    "x",
    "x formerly twitter",
}
MACHINE_ID_PATTERN = re.compile(r"^(?:[0-9a-f]{10,}|[0-9A-HJKMNP-TV-Z]{12,})$", re.IGNORECASE)
TEXT_TOKEN_SPLIT_PATTERN = re.compile(r"[\n,，;；、|]+")
TEXT_SOURCE_NOISE = {
    "about",
    "apple",
    "browse",
    "browsing",
    "browser",
    "chrome",
    "com",
    "edge",
    "firefox",
    "gmail",
    "google",
    "github",
    "homepage",
    "iphone",
    "local",
    "login",
    "mail",
    "media",
    "notification",
    "notifications",
    "page",
    "reddit",
    "safari",
    "search",
    "software",
    "tabs",
    "timeline",
    "user",
    "visited",
    "youtube",
    "关于",
    "使用",
    "查看",
    "浏览",
    "浏览器",
    "搜索",
    "访问",
    "通知",
    "邮件",
    "收件箱",
    "首页",
    "页面",
    "时间线",
    "相关",
    "登录",
    "动态",
    "应用",
}
# Connector words ignored when judging whether a multi-word phrase is
# composed purely of source-noise vocabulary.
TEXT_NEUTRAL_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
OPERATIONAL_ARTIFACT_EXTENSIONS = {
    ".db",
    ".env",
    ".json",
    ".lock",
    ".log",
    ".md",
    ".pid",
    ".sh",
    ".sock",
    ".sqlite",
    ".sqlite3",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
CODE_ARTIFACT_EXTENSIONS = {
    ".js",
    ".jsx",
    ".py",
    ".ts",
    ".tsx",
}
ARTIFACT_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_@~./\\-]+\.[A-Za-z0-9_@./\\-]+")


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _canonical_anchor(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def _anchor_leaf(value: Any) -> str:
    text = str(value or "").strip()
    if ":" in text:
        _, _, text = text.partition(":")
    return text.strip()


def _normalized_match_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def is_generic_experience_anchor(value: Any) -> bool:
    """Return True when an anchor is too generic to justify an experience."""
    raw = str(value or "").strip()
    leaf = _anchor_leaf(raw)
    canonical_values = {_canonical_anchor(raw), _canonical_anchor(leaf)}
    if not raw or not leaf:
        return True
    if _canonical_anchor(raw).startswith("hardware:"):
        return True
    if MACHINE_ID_PATTERN.fullmatch(raw) or MACHINE_ID_PATTERN.fullmatch(leaf):
        return True
    return any(item in GENERIC_EXPERIENCE_ANCHORS for item in canonical_values)


def is_technical_artifact_experience_token(value: Any) -> bool:
    """Return True when text is a low-level file/script/log artifact."""
    text = str(value or "").strip().casefold()
    if not text:
        return False
    for match in ARTIFACT_TOKEN_PATTERN.findall(text):
        token = match.strip(" \t\r\n.。:：()（）[]【】<>《》")
        if not token:
            continue
        leaf = re.split(r"[/\\]", token)[-1]
        if "." not in leaf:
            continue
        stem, extension = leaf.rsplit(".", 1)
        extension = f".{extension}"
        if extension in OPERATIONAL_ARTIFACT_EXTENSIONS:
            return True
        is_file_like = (
            "/" in token
            or "\\" in token
            or "-" in stem
            or "_" in stem
            or stem in {"app", "client", "config", "index", "main", "server", "test", "tests"}
        )
        if extension in CODE_ARTIFACT_EXTENSIONS and is_file_like:
            return True
    return False


def readable_anchor_label(value: Any) -> str:
    """Convert a concrete anchor into a compact human-readable label."""
    leaf = _anchor_leaf(value)
    if not leaf or is_generic_experience_anchor(value) or is_technical_artifact_experience_token(value):
        return ""
    label = leaf.replace("_", " ").replace("-", " ").strip()
    if "/" in label:
        return label
    return " ".join(word.capitalize() for word in label.split())


def _seed_id(seed_type: str, key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"seed-{seed_type}-{digest}"


def _episode_title(episode: Mapping[str, Any]) -> str:
    for key in ("user_label", "label", "summary"):
        value = str(episode.get(key) or "").strip()
        if value:
            return value
    return "Selected experience"


def _episode_concrete_entity_ids(episode: Mapping[str, Any]) -> list[str]:
    return _ordered_unique(
        entity
        for entity in episode.get("primary_entity_ids") or []
        if not is_generic_experience_anchor(entity)
    )


def _episode_concrete_place_ids(episode: Mapping[str, Any]) -> list[str]:
    return _ordered_unique(
        place
        for place in episode.get("primary_place_ids") or []
        if not is_generic_experience_anchor(place)
    )


def _episode_concrete_topic_keys(episode: Mapping[str, Any]) -> list[str]:
    return _ordered_unique(
        topic
        for topic in episode.get("primary_topic_keys") or []
        if not is_generic_experience_anchor(topic)
        and not is_technical_artifact_experience_token(topic)
    )


def _project_anchor_items(episode: Mapping[str, Any]) -> list[tuple[str, str]]:
    anchors: list[tuple[str, str]] = []
    for raw in episode.get("primary_entity_ids") or []:
        text = str(raw or "").strip()
        if is_generic_experience_anchor(text):
            continue
        label = readable_anchor_label(text)
        if not label:
            continue
        lowered = text.casefold()
        if lowered.startswith("project:") or "/" in text:
            anchors.append((text, label))
    return anchors


def _readable_text_token(token: str) -> str:
    text = str(token or "").strip()
    if not text:
        return ""
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    return " ".join(part.capitalize() for part in text.replace("_", " ").split())


def _is_text_noise(token: str) -> bool:
    text = str(token or "").strip().casefold()
    if not text:
        return True
    if len(text) > 40:
        return True
    if is_technical_artifact_experience_token(text):
        return True
    if is_generic_experience_anchor(text):
        return True
    canonical = _canonical_anchor(text)
    if canonical in TEXT_SOURCE_NOISE:
        return True
    if MACHINE_ID_PATTERN.fullmatch(text):
        return True
    if _is_source_noise_phrase(text):
        return True
    return False


def _is_source_noise_phrase(text: str) -> bool:
    """True when every content word of a multi-word phrase is source noise.

    Episode labels such as "Browse Chrome and Google Search" survive the
    single-token noise checks because the phrase as a whole is not in
    ``TEXT_SOURCE_NOISE``. Judge the individual words instead, ignoring
    connector words.
    """
    words = [word for word in re.split(r"[\s./_-]+", text) if word]
    if len(words) < 2:
        return False
    content_words = [word for word in words if word not in TEXT_NEUTRAL_WORDS]
    if not content_words:
        return True
    return all(word in TEXT_SOURCE_NOISE for word in content_words)


def _text_tokens(value: str) -> list[str]:
    """Extract explicit reusable text anchors without free-form n-gram slicing."""
    tokens: list[str] = []
    for raw in TEXT_TOKEN_SPLIT_PATTERN.split(value or ""):
        token = raw.strip(" \t\r\n.。:：()（）[]【】<>《》")
        if not token or _is_text_noise(token):
            continue
        if re.search(r"[\u4e00-\u9fff]", token):
            if len(_normalized_match_text(token)) < 3:
                continue
            tokens.append(token)
        else:
            if len(_normalized_match_text(token)) < 4:
                continue
            if not re.search(r"[\s./_-]", token):
                continue
            tokens.append(token.casefold())
    return _ordered_unique(tokens)


def _source_entity_label_variants(anchor: Any) -> set[str]:
    text = str(anchor or "").strip()
    if not text.casefold().startswith(("software:", "hardware:")):
        return set()
    leaf = _anchor_leaf(text)
    variants = {
        leaf,
        leaf.replace("-", " "),
        leaf.replace("_", " "),
        readable_anchor_label(text),
    }
    if "." in leaf:
        variants.add(leaf.split(".", 1)[0])
    return {
        normalized
        for value in variants
        if (normalized := _normalized_match_text(value))
    }


def _token_matches_source_entity(
    token: str,
    features: Sequence[_EpisodeSeedFeatures],
) -> bool:
    normalized_token = _normalized_match_text(token)
    if not normalized_token:
        return True
    matched = 0
    for feature in features:
        variants = {
            variant
            for entity_id in feature.episode.get("primary_entity_ids") or []
            for variant in _source_entity_label_variants(entity_id)
        }
        if normalized_token in variants:
            matched += 1
    return matched > 0
