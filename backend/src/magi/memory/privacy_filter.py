"""Two-layer privacy filter for source ingestion and cloud LLM egress."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
import ipaddress
import json
import re
from typing import Any, Literal
from urllib.parse import urlparse

from ..config import get_config, get_loader
from ..config.memory_models import PrivacyFilterSettings
from ..utils.log_redaction import MASKED_LOG_VALUE, redact_log_text

PrivacyAction = Literal["allow", "local_only", "drop"]

_LOCAL_PROVIDER_NAMES = frozenset(
    {
        "local",
        "ollama",
        "lmstudio",
        "lm_studio",
        "llama_cpp",
        "llamacpp",
        "vllm_local",
        "mlx",
    }
)
_LOCAL_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "host.docker.internal",
    }
)

_URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]{}]+", re.IGNORECASE)
_PATH_TOKEN_RE = re.compile(
    r"(?:~|/|[A-Za-z]:\\|\.{1,2}/)[A-Za-z0-9._/\\-]+"
    r"|\b[A-Za-z0-9._-]+\.(?:env|pem|p12|pfx|kdbx|key)\b"
    r"|\b\.env(?:\.[A-Za-z0-9._-]+)?\b"
    r"|\bid_(?:rsa|ed25519|ecdsa)\b",
    re.IGNORECASE,
)

# High-confidence cloud egress secret & PII patterns complementing log_redaction.py
_EXTRA_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-(?:live|test|ant|proj|or-v1)?[-_]?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:pk_live|rk_live|whsec)_[A-Za-z0-9_-]{12,}\b"),
)
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_CN_ID_RE = re.compile(
    r"(?<!\d)[1-8]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)
_US_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

_URL_METADATA_KEYS = (
    "url",
    "page_url",
    "href",
    "link",
    "uri",
    "target_url",
    "referrer",
)
_DOMAIN_METADATA_KEYS = (
    "domain",
    "host",
    "hostname",
    "origin",
)
_PATH_METADATA_KEYS = (
    "path",
    "file_path",
    "filepath",
    "cwd",
    "working_directory",
    "directory",
    "target_path",
)
_TEXT_METADATA_KEYS = (
    "command",
    "cmd",
    "title",
    "page_title",
    "summary",
)


@dataclass(frozen=True, slots=True)
class PrivacyDecision:
    """Result of evaluating privacy rules on an event or record."""

    action: PrivacyAction = "allow"
    matched_rule: str | None = None
    reason: str | None = None


def resolve_privacy_filter_settings(
    settings: PrivacyFilterSettings | None = None,
) -> PrivacyFilterSettings:
    """Resolve active PrivacyFilterSettings without triggering blocking config disk I/O."""
    if settings is not None:
        return settings
    try:
        loader = get_loader()
        cfg = getattr(loader, "_config", None) if loader is not None else None
        resolved = getattr(getattr(getattr(cfg, "agent", None), "memory", None), "privacy_filter", None)
        if isinstance(resolved, PrivacyFilterSettings):
            return resolved
    except Exception:
        pass
    return PrivacyFilterSettings()


def is_local_llm_provider(
    *,
    provider: str | None = None,
    base_url: str | None = None,
) -> bool:
    """Return True when the LLM target runs locally rather than on a remote cloud API."""
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider in _LOCAL_PROVIDER_NAMES:
        return True
    raw_url = str(base_url or "").strip()
    if not raw_url:
        return False
    parsed = urlparse(raw_url if "://" in raw_url else f"http://{raw_url}")
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in _LOCAL_HOSTNAMES or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def is_active_chat_llm_local(config: Any | None = None) -> bool:
    """Inspect active core chat LLM configuration; fail closed (False = cloud) when unknown."""
    try:
        cfg = config if config is not None else get_config()
        llm_cfg = getattr(cfg, "llm", None)
        if llm_cfg is None:
            return False
        selections = getattr(llm_cfg, "selections", None) or {}
        providers = getattr(llm_cfg, "providers", None) or {}
        core_sel = selections.get("core")
        if core_sel is None:
            return False
        provider_id = getattr(core_sel, "provider_id", None)
        if not provider_id:
            return False
        provider_cfg = providers.get(provider_id)
        if provider_cfg is None:
            return False
        provider_type = getattr(provider_cfg, "provider_type", None)
        provider_type_str = getattr(provider_type, "value", str(provider_type or ""))
        base_url = getattr(provider_cfg, "base_url", None)
        return is_local_llm_provider(provider=provider_type_str, base_url=base_url)
    except Exception:
        return False


def parse_event_metadata(raw: Any) -> dict[str, Any]:
    """Decode event metadata_json defensively into a dictionary."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            return {}
    return {}


def is_excluded_from_llm(metadata_or_event: Mapping[str, Any] | None) -> bool:
    """Return True when a record is explicitly marked local-only / excluded from cloud LLM."""
    if not isinstance(metadata_or_event, Mapping):
        return False
    if _metadata_has_exclude_flag(metadata_or_event):
        return True
    nested = parse_event_metadata(metadata_or_event.get("metadata_json"))
    if nested and _metadata_has_exclude_flag(nested):
        return True
    nested_meta = parse_event_metadata(metadata_or_event.get("metadata"))
    if nested_meta and _metadata_has_exclude_flag(nested_meta):
        return True
    return False


def _metadata_has_exclude_flag(meta: Mapping[str, Any]) -> bool:
    if bool(meta.get("exclude_from_llm")):
        return True
    if str(meta.get("privacy_level") or "").strip().lower() == "private":
        return True
    privacy = meta.get("privacy")
    if isinstance(privacy, Mapping) and bool(privacy.get("exclude_from_llm")):
        return True
    return False


def _luhn_valid(digits: str) -> bool:
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    if len(set(digits)) == 1:
        return False
    total = 0
    reverse_digits = digits[::-1]
    for idx, ch in enumerate(reverse_digits):
        val = ord(ch) - 48
        if idx % 2 == 1:
            val *= 2
            if val > 9:
                val -= 9
        total += val
    return total % 10 == 0


def _redact_bank_cards(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"[ -]", "", raw)
        if _luhn_valid(digits):
            return "[REDACTED_CARD]"
        return raw

    return _CARD_CANDIDATE_RE.sub(_replace, text)


def redact_cloud_egress_text(text: str) -> tuple[str, bool]:
    """Deterministically redact secrets, tokens, payment cards, and ID numbers for cloud egress."""
    if not text:
        return text, False
    updated = redact_log_text(text)
    for pattern in _EXTRA_SECRET_PATTERNS:
        updated = pattern.sub(MASKED_LOG_VALUE, updated)
    updated = _redact_bank_cards(updated)
    updated = _CN_ID_RE.sub("[REDACTED_ID]", updated)
    updated = _US_SSN_RE.sub("[REDACTED_ID]", updated)
    return updated, updated != text


def redact_structured_for_cloud(value: Any) -> tuple[Any, bool]:
    """Recursively redact strings inside structured payloads before cloud LLM egress."""
    if isinstance(value, str):
        return redact_cloud_egress_text(value)
    if isinstance(value, list):
        changed = False
        out: list[Any] = []
        for item in value:
            redacted_item, item_changed = redact_structured_for_cloud(item)
            changed = changed or item_changed
            out.append(redacted_item)
        return out, changed
    if isinstance(value, tuple):
        changed = False
        out_items: list[Any] = []
        for item in value:
            redacted_item, item_changed = redact_structured_for_cloud(item)
            changed = changed or item_changed
            out_items.append(redacted_item)
        return tuple(out_items), changed
    if isinstance(value, dict):
        changed = False
        out_dict: dict[Any, Any] = {}
        for k, v in value.items():
            redacted_val, val_changed = redact_structured_for_cloud(v)
            changed = changed or val_changed
            out_dict[k] = redacted_val
        return out_dict, changed
    return value, False


def _extract_urls_and_domains(content: str, metadata: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    domains: list[str] = []

    def _add_url(candidate: str) -> None:
        cleaned = candidate.strip()
        if not cleaned:
            return
        urls.append(cleaned)
        parsed = urlparse(cleaned if "://" in cleaned else f"https://{cleaned}")
        host = str(parsed.hostname or "").strip().lower()
        if host:
            domains.append(host)

    for key in _URL_METADATA_KEYS:
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            _add_url(val)

    for key in _DOMAIN_METADATA_KEYS:
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            host = val.strip().lower()
            if "://" in host:
                _add_url(host)
            else:
                domains.append(host.split("/")[0].split(":")[0])

    timeline = metadata.get("timeline")
    if isinstance(timeline, Mapping):
        for key in (*_URL_METADATA_KEYS, *_DOMAIN_METADATA_KEYS):
            val = timeline.get(key)
            if isinstance(val, str) and val.strip():
                if key in _DOMAIN_METADATA_KEYS and "://" not in val:
                    domains.append(val.strip().lower().split("/")[0].split(":")[0])
                else:
                    _add_url(val)

    for text in _iter_candidate_texts(content, metadata):
        for match in _URL_RE.findall(text):
            _add_url(match)

    return urls, domains


def _extract_paths(content: str, metadata: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in _PATH_METADATA_KEYS:
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            paths.append(val.strip())
    for text in _iter_candidate_texts(content, metadata):
        for match in _PATH_TOKEN_RE.findall(text):
            if match:
                paths.append(match.strip())
    return paths


def _iter_candidate_texts(content: str, metadata: Mapping[str, Any]) -> list[str]:
    texts: list[str] = []
    if content:
        texts.append(content)
    for key in _TEXT_METADATA_KEYS:
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            texts.append(val)
    return texts


def _match_domain_or_url_pattern(
    pattern: str,
    *,
    urls: list[str],
    domains: list[str],
) -> bool:
    pat = str(pattern or "").strip().lower()
    if not pat:
        return False

    has_path_or_query = "/" in pat or "?" in pat or "=" in pat
    if not has_path_or_query:
        for host in domains:
            if "*" in pat or "?" in pat:
                if fnmatch(host, pat):
                    return True
            elif host == pat or host.endswith(f".{pat}"):
                return True
        return False

    # URL/path/query pattern
    for url in urls:
        lowered = url.lower()
        stripped = re.sub(r"^[a-z][a-z0-9+.-]*://", "", lowered)
        if "*" in pat or "?" in pat:
            if fnmatch(lowered, pat) or fnmatch(stripped, pat) or fnmatch(stripped, f"*{pat}*"):
                return True
        elif pat in lowered or pat in stripped:
            return True
    return False


def _match_path_pattern(pattern: str, *, paths: list[str]) -> bool:
    pat = str(pattern or "").strip().lower().replace("\\", "/")
    if not pat:
        return False
    for raw_path in paths:
        normalized = raw_path.strip().lower().replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        if fnmatch(normalized, pat) or fnmatch(basename, pat):
            return True
        if "/" in pat and fnmatch(f"/{normalized.lstrip('/')}", pat):
            return True
    return False


def evaluate_source_privacy(
    *,
    source_name: str = "",
    content: str = "",
    metadata: Mapping[str, Any] | None = None,
    settings: PrivacyFilterSettings | None = None,
) -> PrivacyDecision:
    """Evaluate configured sensitive domain, file path, and secret rules."""
    _ = source_name
    cfg = resolve_privacy_filter_settings(settings)
    meta = dict(metadata or {})

    if is_excluded_from_llm(meta):
        return PrivacyDecision(
            action="local_only",
            matched_rule="exclude_from_llm",
            reason="explicit_local_only",
        )

    if not cfg.enabled:
        return PrivacyDecision(action="allow")

    action: PrivacyAction = "drop" if cfg.default_action == "drop" else "local_only"
    urls, domains = _extract_urls_and_domains(content, meta)
    for pattern in cfg.blocked_domain_patterns:
        if _match_domain_or_url_pattern(pattern, urls=urls, domains=domains):
            return PrivacyDecision(
                action=action,
                matched_rule=pattern,
                reason="blocked_domain_pattern",
            )

    paths = _extract_paths(content, meta)
    for pattern in cfg.blocked_path_patterns:
        if _match_path_pattern(pattern, paths=paths):
            return PrivacyDecision(
                action=action,
                matched_rule=pattern,
                reason="blocked_path_pattern",
            )

    for text in _iter_candidate_texts(content, meta):
        _, changed = redact_cloud_egress_text(text)
        if changed:
            return PrivacyDecision(
                action=action,
                matched_rule="secret_or_pii",
                reason="sensitive_secret_detected",
            )

    return PrivacyDecision(action="allow")


def should_exclude_event_from_llm(
    event: Mapping[str, Any],
    *,
    is_local_provider: bool,
    settings: PrivacyFilterSettings | None = None,
) -> bool:
    """Return True if an already-stored event must be omitted from the target LLM provider."""
    if is_local_provider:
        return False
    meta = parse_event_metadata(event.get("metadata_json"))
    if is_excluded_from_llm(event) or is_excluded_from_llm(meta):
        return True
    decision = evaluate_source_privacy(
        source_name=str(event.get("source") or ""),
        content=str(event.get("content") or ""),
        metadata=meta,
        settings=settings,
    )
    return decision.action != "allow"


__all__ = [
    "PrivacyAction",
    "PrivacyDecision",
    "evaluate_source_privacy",
    "is_active_chat_llm_local",
    "is_excluded_from_llm",
    "is_local_llm_provider",
    "parse_event_metadata",
    "redact_cloud_egress_text",
    "redact_structured_for_cloud",
    "resolve_privacy_filter_settings",
    "should_exclude_event_from_llm",
]
