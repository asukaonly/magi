"""Text observations for local reads, search matches, diffs, and command output."""

from __future__ import annotations

from typing import Any

from .tool_output_text import TextBudget, clip_text, one_line


def render_local_result(
    tool_name: str, data: dict[str, Any], *, success: bool, error_code: str | None,
    max_items: int, max_text_chars: int, max_chars: int,
) -> str | None:
    if tool_name in {"bash", "powershell"} and "return_code" in data:
        return _shell(data, success=success, error_code=error_code, max_chars=max_chars)
    if not success:
        return None
    if tool_name == "file_read":
        return _file_read(data, max_chars=max_chars)
    if tool_name in {"file_list", "glob"}:
        return _paths(tool_name, data, max_items=max_items, max_chars=max_chars)
    if tool_name == "grep":
        return _grep(data, max_items=max_items, line_limit=max_text_chars, max_chars=max_chars)
    if tool_name == "file_diff":
        return _diff(data, max_items=max_items, max_chars=max_chars)
    if tool_name == "read_chat_attachment" and data.get("content_kind") == "text":
        return _attachment(data, max_chars=max_chars)
    return None


def _shell(data: dict[str, Any], *, success: bool, error_code: str | None, max_chars: int) -> str:
    out = TextBudget(max_chars)
    status = "succeeded" if success else "failed"
    header = f"Command {status}; exit code: {data.get('return_code')}"
    if error_code:
        header += f"; {one_line(error_code)}"
    if data.get("timed_out"):
        header += "; timed out"
    out.add(header)
    streams = [(name, str(data.get(name) or "")) for name in ("stdout", "stderr")]
    streams = [(name, text) for name, text in streams if text or data.get(f"{name}_truncated")]
    if not streams:
        out.add("No command output.")
    for index, (name, text) in enumerate(streams):
        label = name
        if data.get(f"{name}_truncated"):
            label += " (execution output was truncated)"
        # Reserve space for stderr even when stdout consumes most of the budget.
        share = max(0, out.remaining // (len(streams) - index) - len(label) - 8)
        out.add(label + ":")
        out.add(clip_text(text, share, tail=True))
    return out.render()


def _file_read(data: dict[str, Any], *, max_chars: int) -> str:
    out = TextBudget(max_chars)
    header = f"File: {data.get('path') or '(unspecified)'}"
    if not out.add(header, reserve=160):
        return "File content omitted: its path exceeds the context budget."
    if data.get("is_complete") is False:
        out.add("The tool returned a partial file; use offset/limit for another range.", reserve=80)
    text = str(data.get("content") or "")
    complete = out.body(text or "[Empty file range]", reserve=100)
    if not complete:
        out.add("Observation shortened; request a smaller file range with offset/limit.")
    return out.render()


def _paths(tool_name: str, data: dict[str, Any], *, max_items: int, max_chars: int) -> str:
    out = TextBudget(max_chars)
    listing = tool_name == "file_list"
    root = data.get("path") if listing else data.get("base_path")
    heading = f"Directory: {root}" if listing else f"Glob: {one_line(data.get('pattern'))}\nBase: {root}"
    if not out.add(heading, reserve=160):
        return "Path listing omitted: its location exceeds the context budget."
    items = data.get("entries" if listing else "matches") or []
    shown = 0
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        path = (item.get("relative_path") or item.get("name")) if listing else item.get("path")
        if not path:
            continue
        kind = "symlink" if item.get("is_symlink") else "directory" if item.get("is_dir") else "file"
        line = f"{path} [{kind}]"
        if not out.add(line, reserve=160):
            break
        shown += 1
    note = f"Returned {shown} of {len(items)} entries."
    if data.get("truncated") or shown < len(items):
        note += " Listing truncated; narrow the path or pattern."
    out.add(note)
    return out.render()


def _grep(data: dict[str, Any], *, max_items: int, line_limit: int, max_chars: int) -> str:
    out = TextBudget(max_chars)
    if not out.add(f"Matches for {one_line(data.get('pattern'))}\nPath: {data.get('path')}", reserve=180):
        return "Matches omitted: the query or path exceeds the context budget."
    items = data.get("matches") or []
    shown = 0
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        heading = f"{item.get('file')}:{item.get('line_number')}"
        if not out.add(heading, reserve=240):
            break
        # Put the matched line first so a large context window cannot hide it.
        lines = [f"> {item.get('line_number')}: {clip_text(str(item.get('content') or ''), line_limit)}"]
        for context in item.get("context_before") or []:
            lines.append(f"  {context.get('line_number')}: {clip_text(str(context.get('content') or ''), line_limit)}")
        for context in item.get("context_after") or []:
            lines.append(f"  {context.get('line_number')}: {clip_text(str(context.get('content') or ''), line_limit)}")
        shown += 1
        if not out.body("\n".join(lines), reserve=160):
            break
    note = f"Returned {shown} of {len(items)} matches."
    if data.get("truncated") or shown < len(items):
        note += " More matches may exist; narrow the query or path."
    out.add(note)
    return out.render()


def _diff(data: dict[str, Any], *, max_items: int, max_chars: int) -> str:
    out = TextBudget(max_chars)
    out.add("File changes:")
    items = data.get("diffs") or []
    shown = 0
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        if not out.add(f"File: {item.get('path')}", reserve=200):
            break
        shown += 1
        if item.get("ok") is False:
            out.body(f"Diff unavailable: {item.get('error') or 'unknown error'}", reserve=100)
            continue
        if item.get("current_sha256") != item.get("recorded_sha256_after"):
            out.add("Current content differs from the recorded edit result.", reserve=100)
        text = "Binary files differ." if item.get("binary") else str(item.get("diff_text") or "No textual changes.")
        if not out.body(text, reserve=100):
            break
    if not items:
        out.add("No recorded edits matched.")
    elif shown < len(items):
        out.add(f"{len(items) - shown} diffs omitted; request a specific path.")
    return out.render()


def _attachment(data: dict[str, Any], *, max_chars: int) -> str:
    out = TextBudget(max_chars)
    attachment = data.get("attachment") or {}
    title = attachment.get("original_name") or attachment.get("attachment_id") or "attachment"
    header = f"Attachment: {title}\nattachment_id: {attachment.get('attachment_id') or '(unspecified)'}"
    if not out.add(header, reserve=240):
        return "Attachment content omitted: its identifier exceeds the context budget."
    if data.get("source_truncated"):
        out.add("The extracted source was truncated; later source content may be unavailable.", reserve=160)
    text = str(data.get("text") or "")
    offset = int(data.get("offset") or 0)
    available = max(0, out.remaining - 162)
    visible = text[:available]
    next_offset = offset + len(visible)
    note = f"Characters {offset}..{next_offset} of {data.get('total_chars')} (end exclusive)."
    if len(visible) < len(text) or data.get("is_complete") is False:
        note += f"\nPartial text; continue with offset={next_offset}."
    out.add(note)
    out.add(visible or "[Empty attachment range]")
    return out.render()
