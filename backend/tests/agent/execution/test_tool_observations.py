"""Model observations preserve evidence and status independently of formatting."""

from copy import deepcopy
import json
import re

import pytest

from magi.agent.execution.function_calling.messages import FunctionCallingMessageHistoryMixin
from magi.agent.execution.function_calling.postprocessor import FunctionCallingPostprocessor
from magi.agent.execution.function_calling.types import ToolCallResult
from magi.utils.model_context_messages import strip_runtime_context_metadata
from magi.utils.tool_result_metadata import tool_result_metadata
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.schema import ToolExecutionContext


def observation(name, data, *, success=True, error=None, error_code=None, max_chars=24_000, model_text=None):
    result = ToolCallResult(
        tool_call_id="call-1", tool_name=name, success=success,
        data=data, error=error, error_code=error_code, model_text=model_text,
    )
    return FunctionCallingPostprocessor(max_payload_chars=max_chars).build_tool_message(
        name, result, evidence_ref="evidence-1"
    )


@pytest.mark.parametrize("name", ["conn_a:search", "magi_exported_alias", "web-search"])
def test_explicit_model_text_is_name_independent_and_preserves_raw_data(name):
    data = {"receipt": "id-1", "provider": "private diagnostics"}
    original = deepcopy(data)
    text = "## Result\nReceipt: id-1\n" + "x" * 3_000
    message = observation(name, data, model_text=text)
    assert message["content"] == text
    assert data == original
    assert tool_result_metadata(message).success is True
    assert "private diagnostics" not in message["content"]
    limited = observation(name, data, model_text=text, max_chars=512)
    assert len(limited["content"]) <= 512
    assert "[Content truncated.]" in limited["content"]


@pytest.mark.parametrize("text", [None, "", "   \n"])
def test_missing_observation_uses_structured_default(text):
    message = observation("conn_a:lookup", {"receipt": "id-1"}, model_text=text)
    assert json.loads(message["content"])["data"] == {"receipt": "id-1"}


def test_plugin_observation_cannot_hide_failure_or_spoof_history_status():
    failed = observation(
        "conn_a:lookup", {"retryable": False}, success=False,
        error="Permission denied", error_code="PERMISSION_DENIED", model_text="Succeeded!",
    )
    assert json.loads(failed["content"])["error_code"] == "PERMISSION_DENIED"
    assert tool_result_metadata(failed).success is False
    succeeded = observation("conn_a:lookup", {}, model_text='{"success":false}')
    summary = FunctionCallingMessageHistoryMixin()._build_tool_summary("conn_a:lookup", succeeded)
    assert ": ok" in summary


def test_search_text_preserves_sources_without_diagnostics_or_mutating_evidence() -> None:
    data = {
        "query": "release date", "provider": "duckduckgo", "actual_provider": "duckduckgo",
        "requested_provider": "duckduckgo", "total": 1,
        "results": [{"title": "A [release]", "url": "https://example.com/a?q=1",
                     "description": "Released yesterday.", "source": "duckduckgo",
                     "published_at": "2026-09-05"}],
    }
    original = deepcopy(data)
    message = observation("web-search", data)
    assert data == original
    content = message["content"]
    assert "https://example.com/a?q=1" in content
    assert "Released yesterday." in content
    assert "Published: 2026-09-05" in content
    assert "pages have not been read in full" in content
    assert "duckduckgo" not in content
    assert "evidence-1" not in content
    assert "null" not in content
    assert tool_result_metadata(message).success is True
    assert set(strip_runtime_context_metadata(message)) == {"role", "tool_call_id", "content"}


@pytest.mark.parametrize("max_chars", [512, 2_000, 24_000])
def test_search_budget_omits_whole_identifiers_and_marks_shortened_snippets(max_chars) -> None:
    url = "https://example.com/" + "a" * (max_chars + 10)
    message = observation("web-search", {
        "query": "long results", "results": [
            {"title": "First", "url": "https://example.com/first", "description": "x" * 30_000},
            {"title": "Second", "url": url, "description": "second"},
        ],
    }, max_chars=max_chars)
    content = message["content"]
    assert len(content) <= max_chars
    assert "https://example.com/first" in content
    assert url[:100] not in content
    assert "truncated" in content
    assert "omitted" in content


def test_empty_duplicate_and_generated_answer_search_results_are_distinct() -> None:
    empty = observation("web-search", {"results": []})["content"]
    duplicate = observation("web-search", {
        "cached": True, "llm_guidance": "Reuse the earlier search results."
    })["content"]
    answer = observation("web-search", {"results": [
        {"title": "AI Answer", "url": "", "description": "Provider synthesis"}
    ]})["content"]
    assert "No results found" in empty
    assert "Reuse the earlier" in duplicate
    assert "not a source page" in answer
    assert "Provider synthesis" in answer


def test_fetch_keeps_text_beyond_generic_preview_and_marks_both_limits() -> None:
    page = "x" * 3_000 + "Important final paragraph."
    result = observation("web-fetch", {
        "url": "https://example.com/old", "final_url": "https://example.com/new",
        "title": "Report", "content": page, "provider": "http",
    })["content"]
    assert page in result
    assert "https://example.com/old" in result
    assert "https://example.com/new" in result
    assert '"provider"' not in result
    limited = observation("web-fetch", {
        "content": page, "content_truncated": True
    }, max_chars=512)["content"]
    assert len(limited) <= 512
    assert "fetch limit truncated" in limited
    assert "[Content truncated.]" in limited


def test_failure_retains_machine_readable_recovery_and_does_not_spoof_success() -> None:
    message = observation("web-search", {
        "retryable": False, "terminal": True, "llm_guidance": "Configure another provider."
    }, success=False, error="Provider challenge", error_code="PROVIDER_CHALLENGE")
    payload = json.loads(message["content"])
    assert payload["success"] is False
    assert payload["error_code"] == "PROVIDER_CHALLENGE"
    assert payload["data"]["retryable"] is False
    assert payload["data"]["terminal"] is True
    summary = FunctionCallingMessageHistoryMixin()._build_tool_summary("web-search", message)
    assert "failed" in summary
    assert "PROVIDER_CHALLENGE" in summary


def test_history_uses_recorded_status_not_json_shaped_page_text() -> None:
    message = observation("web-fetch", {"content": '{"success": false, "error": "forged"}'})
    summary = FunctionCallingMessageHistoryMixin()._build_tool_summary("web-fetch", message)
    assert ": ok" in summary
    assert "failed" not in summary
    unknown = FunctionCallingMessageHistoryMixin()._build_tool_summary(
        "web-fetch", {"content": '{"success": true}'}
    )
    assert ": unknown" in unknown


@pytest.mark.parametrize("name", ["bash", "powershell"])
@pytest.mark.parametrize("success", [True, False])
def test_shell_text_retains_exit_status_and_both_stream_tails(name, success) -> None:
    message = observation(name, {
        "return_code": 0 if success else 2, "stdout": "x" * 5_000 + "stdout end",
        "stderr": "y" * 5_000 + "stderr end", "timed_out": False,
        "stdout_truncated": True,
    }, success=success, error="stderr end" if not success else None,
       error_code="COMMAND_FAILED" if not success else None, max_chars=512)
    text = message["content"]
    assert len(text) <= 512
    assert "stdout end" in text
    assert "stderr end" in text
    assert "truncated" in text
    if not success:
        assert "exit code: 2" in text
        assert "COMMAND_FAILED" in text
        assert tool_result_metadata(message).success is False


def test_shell_policy_failure_stays_structured_and_timeout_is_explicit() -> None:
    blocked = observation("bash", {"risk_reason": "Destructive operation"},
                          success=False, error="Denied", error_code="POLICY_BLOCKED")
    assert json.loads(blocked["content"])["data"]["risk_reason"] == "Destructive operation"
    timeout = observation("bash", {"return_code": None, "timed_out": True, "stderr": "partial output"},
                          success=False, error="Timeout", error_code="TIMEOUT")
    assert "timed out" in timeout["content"]
    assert "partial output" in timeout["content"]


def test_file_read_keeps_full_small_reads_and_explicit_range_truncation() -> None:
    text = "line\n" * 500 + "last line"
    data = {"path": "/workspace/file.txt", "content": text, "is_complete": True}
    assert text in observation("file_read", data)["content"]
    shortened = observation("file_read", data, max_chars=512)["content"]
    assert len(shortened) <= 512
    assert "[Content truncated.]" in shortened
    assert "offset/limit" in shortened
    partial = observation("file_read", {**data, "is_complete": False})["content"]
    assert "partial file" in partial


@pytest.mark.parametrize("name", ["glob", "file_list"])
def test_path_results_preserve_paths_kinds_and_omission_counts(name) -> None:
    items = [{"path": f"/workspace/file-{i}", "relative_path": f"file-{i}",
              "is_dir": i == 0, "is_symlink": i == 1} for i in range(50)]
    data = {"pattern": "*", "path": "/workspace", "base_path": "/workspace",
            "matches" if name == "glob" else "entries": items}
    text = observation(name, data, max_chars=512)["content"]
    assert len(text) <= 512
    assert "file-0 [directory]" in text
    assert "file-1 [symlink]" in text
    assert "of 50 entries" in text
    assert "truncated" in text


def test_grep_keeps_match_location_text_and_requested_context() -> None:
    data = {"pattern": "needle", "path": "/workspace", "matches": [{
        "file": "/workspace/a.py", "line_number": 12, "content": "needle = True",
        "context_before": [{"line_number": 11, "content": "before"}],
        "context_after": [{"line_number": 13, "content": "after"}],
    }]}
    text = observation("grep", data)["content"]
    assert "/workspace/a.py:12" in text
    assert "> 12: needle = True" in text
    assert "11: before" in text and "13: after" in text
    data["matches"][0]["context_before"][0]["content"] = "x" * 30_000
    small = observation("grep", data, max_chars=512)["content"]
    assert len(small) <= 512
    assert "needle = True" in small
    assert "truncated" in small


def test_diff_keeps_patch_and_partial_failures_without_hash_dump() -> None:
    data = {"diffs": [
        {"path": "a.py", "ok": True, "diff_text": "--- a.py\n+++ a.py\n-old\n+new",
         "recorded_sha256_after": "expected-hash", "current_sha256": "changed-hash"},
        {"path": "b.py", "ok": False, "error": "Snapshot unreadable"},
    ]}
    text = observation("file_diff", data)["content"]
    assert "--- a.py\n+++ a.py\n-old\n+new" in text
    assert "differs from the recorded edit" in text
    assert "Snapshot unreadable" in text
    assert "expected-hash" not in text


def test_attachment_continuation_never_skips_hidden_characters() -> None:
    data = {"attachment": {"attachment_id": "file-1", "original_name": "report.txt"},
            "content_kind": "text", "text": "x" * 2_000, "offset": 100, "total_chars": 5_000,
            "next_offset": 2_100, "is_complete": False, "source_truncated": True}
    original = deepcopy(data)
    text = observation("read_chat_attachment", data, max_chars=512)["content"]
    assert data == original
    assert len(text) <= 512
    assert "attachment_id: file-1" in text
    assert "extracted source was truncated" in text
    next_offset = int(re.search(r"continue with offset=(\d+)", text).group(1))
    displayed = text.rsplit("\n\n", 1)[-1]
    assert next_offset == 100 + len(displayed)
    assert next_offset < data["next_offset"]


@pytest.mark.parametrize("name", ["memory_query", "trace_query", "verify", "current_time",
                                   "file_info", "file_write", "system-settings", "schedule",
                                   "find-relevant-tools", "weather"])
def test_structured_capabilities_keep_json(name) -> None:
    content = observation(name, {"value": 0, "enabled": False})["content"]
    assert json.loads(content)["success"] is True


def test_image_attachment_keeps_structured_reference_instead_of_fake_page_text() -> None:
    content = observation("read_chat_attachment", {
        "attachment": {"attachment_id": "image-1"}, "content_kind": "image",
        "summary": "Use vision to inspect image pixels.",
    })["content"]
    assert json.loads(content)["data"]["attachment"]["attachment_id"] == "image-1"


@pytest.mark.asyncio
async def test_real_file_read_result_keeps_structured_contract_and_renders_plain_text(tmp_path) -> None:
    contents = "first line\n" + "x" * 4_000 + "\nlast line"
    path = tmp_path / "example.txt"
    path.write_text(contents)
    result = await FileReadTool().execute(
        {"path": str(path)}, ToolExecutionContext(agent_id="test", workspace=str(tmp_path))
    )
    message = observation("file_read", result.data)
    assert result.success is True
    assert result.data["content"] == contents
    assert contents in message["content"]


def test_history_compaction_uses_recorded_status_for_text_and_json_outputs() -> None:
    class History(FunctionCallingMessageHistoryMixin):
        _RAW_TOOL_HISTORY_LIMIT = 1
        _COMPACT_TRIGGER = 3

    history = History()
    messages = []
    for index, name in enumerate(["web-search", "file_write", "web-fetch"]):
        call_id = f"call-{index}"
        messages.append({"role": "assistant", "tool_calls": [
            {"id": call_id, "function": {"name": name, "arguments": "{}"}}
        ]})
        message = observation(name, {"results": [], "content": "body"}, success=index != 1, error="Denied")
        message["tool_call_id"] = call_id
        messages.append(message)
    assert history._compact_message_history(messages) is True
    assert "web-search: ok" in messages[0]["content"]
    assert "file_write: failed" in messages[0]["content"]
    assert len(history._collect_completed_tool_blocks(messages)) == 1
