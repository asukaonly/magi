"""Prompt construction and plain-chat LLM calls for chat task agents."""
from __future__ import annotations

import json
import re
from typing import Any

from ....config.models import LLMScenario
from ...orchestration import WorkerResult
from ..common import TaskAgentLLMService
from .contracts import ChatReplyContext


class ChatPromptService:
    """Owns direct LLM invocation and chat prompt helper text."""

    def __init__(
        self,
        *,
        llm_adapter=None,
        llm_pool=None,
    ) -> None:
        self._llm = llm_adapter
        self._llm_pool = llm_pool
        self._llm_service = TaskAgentLLMService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            scenario=LLMScenario.CORE,
            logger_name="chat",
        )

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        llm_trace_callback=None,
    ) -> str:
        return await self._llm_service.call(
            system_prompt=system_prompt,
            messages=messages,
            disable_thinking=disable_thinking,
            temperature=0.7,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            llm_trace_callback=llm_trace_callback,
        )

    def filter_history_for_aggregation(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        filtered: list[dict[str, str]] = []
        for item in history[-8:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content or content.startswith("[Worker:"):
                continue
            filtered.append({"role": role, "content": content})
        return filtered

    def build_aggregation_payload(self, state) -> dict[str, Any]:
        return {
            "user_request": state.root_user_message,
            "planner": state.planner,
            "completed_subtasks": [
                {
                    "subtask_id": item.subtask_id,
                    "description": item.description,
                    "result": item.worker_result.to_dict(),
                }
                for item in state.subtasks
                if item.status == "completed" and isinstance(item.worker_result, WorkerResult)
            ],
            "failed_subtasks": [
                {
                    "subtask_id": item.subtask_id,
                    "description": item.description,
                    "failure_reason": item.failure_reason,
                    "attempt_count": item.attempt_count,
                }
                for item in state.subtasks
                if item.status == "failed"
            ],
        }

    def build_aggregation_system_prompt(
        self,
        *,
        base_system_prompt: str,
        state,
        payload: dict[str, Any],
    ) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False)
        research_requirements = self._build_research_aggregation_requirements(state.root_user_message)
        if self.prefers_chinese_response(state.root_user_message):
            lines = [
                base_system_prompt.strip(),
                "",
                f"用户原始请求：{state.root_user_message}",
                "你已经拿到了内部子任务的结构化结果。现在请直接面向用户回答原始请求。",
                "要求：",
                "- 使用自然、正常的聊天语气，不要暴露子任务、worker、编排、JSON 或内部流程。",
                "- 优先整合已经确认的信息，并在合适的时候引用关键文件路径作为依据。",
                "- 对失败的部分，只需要简短说明哪些方面还没完全确认，不要把失败列表原样抄给用户。",
                "- 如果已有信息不足以完整覆盖原问题，就先给出当前最可靠的结论，再明确缺口。",
                "- 回复语言跟随用户。",
            ]
            lines.extend(research_requirements["zh"])
            lines.extend(["", f"内部结果(JSON): {payload_json}"])
            return "\n".join(lines).strip()
        lines = [
            base_system_prompt.strip(),
            "",
            f"Original user request: {state.root_user_message}",
            "You already have the structured results from internal leaf tasks. Now answer the original request directly to the user.",
            "Requirements:",
            "- Respond in a natural conversational style and do not mention subtasks, workers, orchestration, JSON, or internal process details.",
            "- Prioritize confirmed information and cite key file paths naturally when they matter.",
            "- For failed areas, briefly mention what remains unconfirmed instead of dumping an internal failure list.",
            "- If the available evidence is incomplete, give the most reliable current conclusion first and then call out the remaining gaps.",
            "- Mirror the user's language.",
        ]
        lines.extend(research_requirements["en"])
        lines.extend(["", f"Internal results (JSON): {payload_json}"])
        return "\n".join(lines).strip()

    def build_explore_render_message(self, root_user_message: str, dossier: str) -> str:
        if self.prefers_chinese_response(root_user_message):
            return "\n".join(
                [
                    f"用户原始请求：{root_user_message}",
                    "下面是一份已经整理好的探索报告，请直接面向用户给出最终回答。",
                    "要求：",
                    "- 使用自然、正常的聊天语气，但必须用清晰的 Markdown 结构来组织内容。",
                    "- 使用 `##` 二级标题组织主要部分；每个主要部分之间保留空行。",
                    "- 关键点尽量用短段落或 `-` 列表，不要输出一整块没有换行的大段文字。",
                    "- 以已经确认的信息为主，必要时自然引用关键文件路径。",
                    "- 对尚未确认的部分，简短说明边界和缺口，不要暴露内部流程。",
                    "- 如果是代码库/架构分析，优先使用这些部分：`## 项目概况`、`## 技术栈`、`## 架构分析`、`## 当前进展与缺口`、`## 总结`。可以按实际情况裁剪。",
                    "",
                    dossier,
                ]
            )
        return "\n".join(
            [
                f"Original user request: {root_user_message}",
                "Below is a prepared exploration dossier. Answer the user directly based on it.",
                "Requirements:",
                "- Use a natural conversational tone, but organize the answer with clear Markdown structure.",
                "- Use `##` section headings and keep a blank line between major sections.",
                "- Prefer short paragraphs or `-` bullets over a single dense wall of text.",
                "- Lead with confirmed findings and cite important file paths naturally when they matter.",
                "- Briefly call out remaining gaps without exposing internal process details.",
                "- For repository or architecture analysis, prefer sections like `## Overview`, `## Stack`, `## Architecture`, `## Gaps`, and `## Summary` when relevant.",
                "",
                dossier,
            ]
        )

    def build_explore_render_fallback(self, root_user_message: str, dossier: str = "") -> str:
        if dossier.strip():
            return self.format_explore_render_response(dossier.strip())
        if self.prefers_chinese_response(root_user_message):
            return "这次探索报告已经完成，但最终整理回答时没有拿到可用文本结果。"
        return "The exploration dossier completed, but the final rendering step did not return usable text."

    def augment_system_prompt_with_reply_context(
        self,
        *,
        system_prompt: str,
        reply_context: ChatReplyContext | None,
    ) -> str:
        reply_block = self.build_reply_context_block(reply_context)
        if not reply_block:
            return system_prompt
        return f"{system_prompt}\n\n{reply_block}"

    def build_reply_context_block(self, reply_context: ChatReplyContext | None) -> str:
        if reply_context is None:
            return ""
        lines = [
            "Current message is replying to:",
            f"- speaker: {reply_context.role}",
            f'- message: "{reply_context.content_excerpt}"',
        ]
        if reply_context.references_prior_turn:
            lines.append("- note: this reply points to an earlier turn, so keep that thread continuity explicit.")
        return "\n".join(lines)

    def format_explore_render_response(self, response_text: str) -> str:
        text = str(response_text or "").replace("\r\n", "\n").strip()
        if not text:
            return text

        if "## " not in text and "### " not in text:
            text = re.sub(r"(?<!\n)(\d+\.\s)", r"\n\n\1", text)
            text = re.sub(r"(?<!\n)(-\s)", r"\n\1", text)

        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def build_aggregation_fallback(self, state) -> str:
        completed = [
            item for item in state.subtasks
            if item.status == "completed" and isinstance(item.worker_result, WorkerResult)
        ]
        failed = [item for item in state.subtasks if item.status == "failed"]
        if self.prefers_chinese_response(state.root_user_message):
            lines = ["我先基于目前已经确认的结果给你一个可用的结论。", ""]
            if completed:
                lines.append("目前已经确认的部分：")
                for item in completed:
                    summary = item.worker_result.summary.strip()
                    if summary:
                        lines.append(f"- {summary}")
            if failed:
                lines.append("")
                lines.append("还有几部分这次没有成功完成，所以相关信息暂时不能完全确认：")
                for item in failed:
                    lines.append(f"- {item.description}")
            return "\n".join(lines).strip()

        lines = ["Here is the most reliable answer I can give based on the completed analysis so far.", ""]
        if completed:
            lines.append("Confirmed so far:")
            for item in completed:
                summary = item.worker_result.summary.strip()
                lines.append(f"- {summary or 'Completed with structured findings.'}")
        if failed:
            lines.append("")
            lines.append("These areas are still not fully confirmed because the underlying worker run failed:")
            for item in failed:
                lines.append(f"- {item.description}")
        return "\n".join(lines).strip()

    def _build_research_aggregation_requirements(self, user_message: str) -> dict[str, list[str]]:
        lowered = user_message.lower()
        if not any(
            keyword in lowered
            for keyword in ["news", "新闻", "资料", "信息", "来源", "链接", "source", "link", "核实", "verify"]
        ):
            return {"zh": [], "en": []}
        return {
            "zh": [
                "- 如果这是新闻或资料汇总类请求，请优先按条列出结果，而不是压成一整段。",
                "- 尽量保留每条结果的标题、日期、来源、链接和简短摘要；不要丢掉时间和来源。",
                "- 如果用户要求条数，在证据足够时尽量满足该条数；不足时明确说明只确认了多少条。",
            ],
            "en": [
                "- For news or research summaries, prefer a structured itemized list instead of one dense paragraph.",
                "- Preserve each item's title, date, source, link, and a short summary whenever the evidence supports it.",
                "- If the user requested a count, satisfy it when the evidence is sufficient; otherwise state how many items were confirmed.",
            ],
        }

    def prefers_chinese_response(self, text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)
