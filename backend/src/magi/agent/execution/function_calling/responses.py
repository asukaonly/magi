"""Final response and tool-result payload helpers for function-calling execution."""

from __future__ import annotations

import re
from typing import Any

from ...asset_refs import normalize_asset_ref_payload
from .types import ToolCallResult

class FunctionCallingResponseMixin:
    """Build final-answer prompts and aggregate tool result presentation data."""

    _FAILED_ITERATION_REPLAN_LIMIT: int
    _NON_REPLAN_ERROR_CODES: set[str]
    _TERMINAL_TOOL_ERROR_CODES: set[str]
    _PARENT_CONTEXT_MAX_MESSAGES: int
    _PARENT_CONTEXT_MAX_CHARS: int
    _current_messages: list[dict[str, Any]]

    def _augment_system_prompt(self, system_prompt: str) -> str:
        guidance = (
            "\n\nTool recovery rules:\n"
            "- When a tool fails, inspect the tool error before deciding the next step.\n"
            "- Do not repeat the same tool call with the same arguments after a failure.\n"
            "- If a call fails because parameters or path selection are wrong, choose a narrower or corrected tool strategy.\n"
            "- If a file scan is blocked because it would leave the workspace and the user did not provide an explicit path, do not broaden the local scan; ask the user for a path or use web-search first.\n"
            "- If grep is blocked or too broad, switch to scoped glob plus file_read before trying again.\n"
            "- If a tool result has retryable=false, terminal=true, or error code PROVIDER_CHALLENGE, NO_PROVIDERS_CONFIGURED, or PROVIDER_NOT_CONFIGURED, do not call that same tool again in the current turn.\n"
            "- Prefer an alternative tool or narrower scope over repeating the failed call unchanged."
            "\n\nTool discovery rules:\n"
            "- Call find-relevant-tools only when the current tool set is missing a needed "
            "capability for the next grounded step.\n"
            "- Query for one focused capability gap at a time; include the domain/action/object "
            "and concrete facts already known, such as time, place, source, path, entity, "
            "or output format.\n"
            "- Do not pass the whole user request, vague phrases, or broad capability-browsing "
            "prompts as the query.\n"
            "- Always pass current_tools with the tools already available in this turn.\n"
            "- After a successful find-relevant-tools call, use newly recommended tools only "
            "if they directly close that gap."
        )
        if guidance.strip() in system_prompt:
            return system_prompt
        return f"{system_prompt}{guidance}"

    def _build_final_response_system_prompt(
        self,
        system_prompt: str,
        *,
        strict_plain_text: bool = False,
    ) -> str:
        """Strip tool-oriented guidance and replace it with final-answer-only rules."""
        prompt = re.split(
            r"(?:^|\n)# Tool (?:Information|Use Guidance)\b",
            system_prompt,
            maxsplit=1,
        )[0]
        prompt = re.split(r"\nTool recovery rules:\n", prompt, maxsplit=1)[0].rstrip()
        rules = [
            "Final Response Rules:",
            "- Tools are no longer available in this step.",
            "- Do not emit tool calls, XML-like <tool_call> blocks, JSON tool payloads, or any protocol markup.",
            "- Use the existing evidence in the conversation and write the final answer directly.",
            "- When tool results conflict, prefer the later tool result over earlier plans, guesses, or dry-run output.",
            "- Treat successful verification and directory-listing tool results as the current state of the world.",
            "- If a dry-run reports zero planned operations, do not tell the user to run the script unless later evidence proves work is still pending; explain whether the current state already appears complete or the script failed to match.",
            "- Return natural language only.",
        ]
        if strict_plain_text:
            rules.extend(
                [
                    "- Do not ask to keep searching or mention missing tools.",
                    "- If evidence is incomplete, clearly state the limitation and still answer with the strongest grounded explanation you can.",
                ]
            )
        if "memory_query" in system_prompt or "# Memory Query Guidance" in system_prompt:
            rules.extend(
                [
                    "- Treat memory_query results as the source of truth for historical recall in this turn.",
                    "- Do not replace missing recall results with implicit memory, prior assumptions, or guesses.",
                    "- Keep historical claims within the returned findings and coverage.",
                    "- Persona or tone may change phrasing, but must not broaden or distort memory evidence.",
                ]
            )
        return f"{prompt}\n\n" + "\n".join(rules)

    def _build_final_response_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        force_plain_text: bool = False,
    ) -> list[dict[str, Any]]:
        """Clone messages and append a final plain-text-only instruction."""
        final_messages = [dict(message) for message in messages]
        reminder = (
            "Use the gathered evidence and write the final answer now. "
            "Prefer the latest successful verification/listing result when describing current state. "
            "Do not call tools or output any tool markup."
        )
        if force_plain_text:
            reminder = (
                "This is the final retry. Write the answer in plain natural language only. "
                "Do not call tools, do not output <tool_call>, and do not output JSON."
            )
        final_messages.append({"role": "user", "content": reminder})
        return final_messages

    def _should_allow_replan_after_failed_iteration(
        self,
        tool_results: list[ToolCallResult],
        *,
        consecutive_failed_tool_iterations: int,
        available_tools: list[dict[str, Any]] | None = None,
    ) -> bool:
        if consecutive_failed_tool_iterations > self._FAILED_ITERATION_REPLAN_LIMIT:
            return False
        error_codes = {
            str(result.error_code or "").strip()
            for result in tool_results
            if str(result.error_code or "").strip()
        }
        if not error_codes:
            return True
        if any(code in self._TERMINAL_TOOL_ERROR_CODES for code in error_codes):
            return False
        has_non_replan_error = any(code in self._NON_REPLAN_ERROR_CODES for code in error_codes)
        if not has_non_replan_error:
            return True
        if available_tools:
            failed_names = {str(result.tool_name) for result in tool_results}
            all_names = {str(tool.get("function", {}).get("name", "")) for tool in available_tools}
            if all_names - failed_names:
                return True
        return False

    def _extract_chat_attachments_from_tool_results(
        self,
        tool_results: list[ToolCallResult],
    ) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        for result in tool_results:
            if not result.success or not isinstance(result.data, dict):
                continue
            tool_attachments = result.data.get("chat_attachments")
            if not isinstance(tool_attachments, list):
                continue
            for item in tool_attachments:
                if isinstance(item, dict):
                    attachments.append(dict(item))
        return attachments

    def _extract_assistant_message_payload_from_tool_results(
        self,
        tool_results: list[ToolCallResult],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for result in tool_results:
            if not isinstance(result.data, dict):
                continue

            nested_payload = result.data.get("assistant_payload")
            if isinstance(nested_payload, dict):
                payload = self._merge_assistant_message_payload(
                    payload,
                    normalize_asset_ref_payload(nested_payload),
                )

            if not result.success:
                continue

            normalized_result = normalize_asset_ref_payload(result.data)
            direct_payload: dict[str, Any] = {}
            asset_refs = normalized_result.get("asset_refs")
            if isinstance(asset_refs, list):
                direct_payload["asset_refs"] = [
                    dict(item) for item in asset_refs if isinstance(item, dict)
                ]
            historical_recall = result.data.get("historical_recall")
            if isinstance(historical_recall, dict):
                recall_asset_refs = historical_recall.get("asset_refs")
                if isinstance(recall_asset_refs, list):
                    direct_payload["asset_refs"] = [
                        dict(item) for item in recall_asset_refs if isinstance(item, dict)
                    ]
                recalled_memories = self._compact_recalled_memories(historical_recall)
                if recalled_memories:
                    direct_payload["recalled_memories"] = recalled_memories
                recalled_memory_summary = self._compact_recalled_memory_summary(historical_recall)
                if recalled_memory_summary:
                    direct_payload["recalled_memory_summary"] = recalled_memory_summary
            payload = self._merge_assistant_message_payload(payload, direct_payload)
        return payload

    def _compact_recalled_memories(
        self,
        historical_recall: dict[str, Any],
        *,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        """Project a historical recall payload into the compact UI-facing form.

        Only the fields the chat shell needs to render the "called memories"
        row and its detail popover are surfaced here. Heavy fields like the
        full LLM-facing summary or trace metadata are intentionally dropped
        to keep the message payload small enough for SQLite/JSON
        round-tripping.
        """
        findings = historical_recall.get("findings")
        if not isinstance(findings, list):
            return []
        compact: list[dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            statement = str(finding.get("statement") or "").strip()
            if not statement:
                continue
            entry: dict[str, Any] = {
                "kind": str(finding.get("kind") or "event"),
                "source_layer": str(finding.get("source_layer") or "L1"),
                "statement": statement,
                "topic": str(finding.get("topic") or "").strip() or statement,
            }
            confidence = finding.get("confidence")
            if isinstance(confidence, (int, float)):
                entry["confidence"] = float(confidence)
            occurred_at = finding.get("occurred_at")
            if isinstance(occurred_at, (int, float)):
                entry["occurred_at"] = float(occurred_at)
            evidence_text = str(finding.get("evidence_text") or "").strip()
            if evidence_text:
                entry["evidence_text"] = evidence_text
            feedback_ref = str(finding.get("feedback_ref") or "").strip()
            if feedback_ref:
                entry["feedback_ref"] = feedback_ref
            compact.append(entry)
            if len(compact) >= limit:
                break
        return compact

    def _compact_recalled_memory_summary(
        self,
        historical_recall: dict[str, Any],
    ) -> dict[str, Any]:
        coverage = historical_recall.get("coverage")
        if not isinstance(coverage, dict):
            return {}
        if not bool(coverage.get("can_claim_total")):
            return {}

        summary: dict[str, Any] = {
            "coverage_kind": str(coverage.get("kind") or "unknown"),
            "can_claim_total": True,
        }
        total_count = coverage.get("total_count")
        if isinstance(total_count, (int, float)):
            summary["total_count"] = int(total_count)

        structured_results = historical_recall.get("structured_results")
        if isinstance(structured_results, list) and structured_results:
            first = structured_results[0]
            if isinstance(first, dict):
                domain = str(first.get("domain") or "").strip()
                if domain:
                    summary["domain"] = domain
                structured_summary = first.get("summary")
                if "total_count" not in summary and isinstance(structured_summary, dict):
                    for key in ("event_count", "session_count"):
                        count = structured_summary.get(key)
                        if isinstance(count, (int, float)):
                            summary["total_count"] = int(count)
                            break
        return summary

    def _merge_assistant_message_payload(
        self,
        base_payload: dict[str, Any] | None,
        incoming_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = normalize_asset_ref_payload(base_payload)
        if not incoming_payload:
            return merged
        for key, value in normalize_asset_ref_payload(incoming_payload).items():
            if key == "attachments":
                continue
            if isinstance(value, list):
                normalized_items = [
                    dict(item) if isinstance(item, dict) else item for item in value
                ]
                existing = merged.get(key)
                if isinstance(existing, list):
                    merged[key] = [*existing, *normalized_items]
                else:
                    merged[key] = normalized_items
                continue
            merged[key] = value
        return merged

    def _classify_final_failure(
        self,
        tool_failures: list[dict[str, Any]],
        all_tools_failed: bool,
    ) -> str:
        if tool_failures and all(
            item.get("error_code") == "AMBIGUOUS_SCOPE" for item in tool_failures
        ):
            return "AMBIGUOUS_SCOPE"
        if tool_failures and all(
            item.get("error_code") == "INVALID_PARAMETERS" for item in tool_failures
        ):
            return "INVALID_TOOL_CALL"
        if all_tools_failed and tool_failures:
            return "ALL_TOOLS_FAILED"
        return "EMPTY_FINAL_RESPONSE"

    def _normalize_agent_launch_arguments(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(arguments)
        action = str(normalized.get("action", "launch"))
        if action != "launch":
            return normalized
        if "run_in_background" not in normalized:
            normalized["run_in_background"] = True

        if normalized.pop("inherit_context", False) and self._current_messages:
            normalized["parent_context_summary"] = self._build_parent_context_summary()

        if not str(normalized.get("subagent_type", "")).strip():
            normalized["subagent_type"] = "general-purpose"
        return normalized

    def _build_parent_context_summary(self) -> str:
        """Build a concise summary of the current conversation for a child worker."""
        from ..context_compactor import ContextCompactor

        messages = self._current_messages
        if not messages:
            return ""

        recent = messages[-self._PARENT_CONTEXT_MAX_MESSAGES :]
        rendered = str(ContextCompactor._render_messages_for_summary(recent))
        if len(rendered) > self._PARENT_CONTEXT_MAX_CHARS:
            rendered = rendered[-self._PARENT_CONTEXT_MAX_CHARS :]
            newline_index = rendered.find("\n")
            if newline_index > 0:
                rendered = rendered[newline_index + 1 :]
        return rendered
