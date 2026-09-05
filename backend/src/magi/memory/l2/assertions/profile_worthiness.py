"""Host-owned semantic checks before behavior becomes a profile assertion."""

from __future__ import annotations

import re
from typing import Any, Mapping

_NAVIGATION_ROLES = frozenset({"navigation", "menu", "page_title", "task_instruction", "search_query", "ui_label"})
_NON_CONTENT_PAGES = frozenset({"home", "homepage", "feed", "search", "search_results", "login", "settings", "navigation", "index"})
_SEMANTIC_ROLES = frozenset({"topic", "creator", "work", "product", "organization", "person"})
_NAV_LABEL = re.compile(r"^(?:首页|动态|消息|通知|设置|搜索|推荐|关注|收藏|home|feed|notifications?|settings|search)(?:\s*[（(]?\d+[)）]?)?$", re.IGNORECASE)
_TASK_LABEL = re.compile(r"^(?:请(?:帮我)?|帮我|替我|实现|修复|修改|总结一下|please\s|(?:implement|fix|update|summari[sz]e)\s)", re.IGNORECASE)


def profile_evidence_reason(event: Mapping[str, Any], *, object_id: str, label: str) -> str | None:
    """Return an exclusion reason; raw events and their behavior edges remain intact."""
    metadata = event.get("metadata_json") or {}
    hints = metadata.get("structured_entity_hints") or []
    matched = [hint for hint in hints if isinstance(hint, dict) and (hint.get("resolved_entity_id") == object_id or label in {hint.get("mention_text"), hint.get("canonical_name_hint")})]
    roles = {str(hint.get("semantic_role") or hint.get("object_role") or "").casefold() for hint in matched}
    roles.add(str(metadata.get("object_role") or "").casefold())
    if metadata.get("profile_eligible") is False or any(hint.get("profile_eligible") is False for hint in matched):
        return "source_excludes_profile"
    if roles & _NAVIGATION_ROLES:
        return "non_profile_object_role"
    # A semantic topic or named work inside a page is distinct from the page's navigation label.
    if roles & _SEMANTIC_ROLES:
        return None
    if str(metadata.get("page_kind") or "").casefold() in _NON_CONTENT_PAGES:
        return "non_content_page"
    if _NAV_LABEL.fullmatch(label.strip()):
        return "navigation_label"
    if _TASK_LABEL.match(label.strip()):
        return "task_instruction_label"
    return None
