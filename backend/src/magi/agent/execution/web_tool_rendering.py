"""Readable observations for web tools; provider diagnostics stay in evidence."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .tool_output_text import TextBudget, clip_text, one_line


def render_web_result(
    tool_name: str, data: dict[str, Any], *, max_items: int, max_text_chars: int, max_chars: int
) -> str | None:
    if tool_name == "web-search":
        return _search(data, max_items=max_items, snippet_limit=max_text_chars, max_chars=max_chars)
    if tool_name == "web-fetch":
        return _fetch(data, max_chars=max_chars)
    return None


def _source_link(title: object, url: object) -> str:
    target = str(url or "").strip()
    try:
        parsed = urlsplit(target)
        is_web_url = parsed.scheme in {"http", "https"}
        hostname = parsed.hostname
    except ValueError:
        is_web_url = False
        hostname = None
    label = one_line(title) or hostname or "Untitled source"
    label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    if not target or not is_web_url:
        return label
    target = target.replace("<", "%3C").replace(">", "%3E").replace("\n", "%0A").replace("\r", "%0D")
    return f"[{label}](<{target}>)"


def _search(data: dict[str, Any], *, max_items: int, snippet_limit: int, max_chars: int) -> str:
    out = TextBudget(max_chars)
    query = clip_text(one_line(data.get("query")), min(400, max_chars // 4))
    out.add(f"Search: {query}\nSearch snippets follow; pages have not been read in full.", reserve=100)
    bounds = data.get("date_range_applied")
    if isinstance(bounds, dict) and bounds:
        hints = ", ".join(f"{key}={one_line(value)}" for key, value in bounds.items())
        out.add(f"Date hints: {hints}. Filtering depends on the provider.", reserve=100)
    results = data.get("results")
    if not isinstance(results, list):
        guidance = str(data.get("llm_guidance") or "No result list returned.")
        out.body(guidance)
        return out.render()
    if not results:
        out.add("No results found.")
        return out.render()
    shown = 0
    for item in results[:max_items]:
        if not isinstance(item, dict):
            continue
        heading = f"{shown + 1}. {_source_link(item.get('title'), item.get('url'))}"
        if not item.get("url"):
            heading += " [Provider-generated answer; not a source page]"
        published = item.get("published_at") or item.get("publishedAt") or item.get("published_date")
        if published:
            heading += f"\nPublished: {one_line(published)}"
        if not out.add(heading, reserve=240):
            break
        shown += 1
        description = str(item.get("description") or "")
        out.body(clip_text(description, snippet_limit), reserve=160)
    note = f"Returned {shown} of {len(results)} results."
    if shown < len(results):
        note += " Results omitted to fit the context budget; refine the query for more."
    out.add(note)
    return out.render()


def _fetch(data: dict[str, Any], *, max_chars: int) -> str:
    out = TextBudget(max_chars)
    url = data.get("final_url") or data.get("url")
    heading = f"Web page: {_source_link(data.get('title'), url)}" if url else "Web page content"
    if not out.add(heading, reserve=180):
        return "Web page result omitted: its source identifier exceeds the context budget."
    original = data.get("url")
    if original and original != url:
        out.add(f"Requested URL: {original}", reserve=180)
    if data.get("content_truncated"):
        out.add("The fetch limit truncated the page; increase max_chars to read more.", reserve=100)
    content = str(data.get("content") or "")
    out.body(content or "No page text returned.")
    return out.render()
