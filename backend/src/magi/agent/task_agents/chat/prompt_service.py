"""Prompt construction and plain-chat LLM calls for chat task agents."""
from __future__ import annotations

import json
import re
from typing import Any

from ....agent import get_unified_memory
from ....context.builder import Scenario
from ....memory.hybrid_retrieval import HybridRetrievalService, build_query
from ....config.models import LLMScenario
from ...orchestration import WorkerResult
from ....context.assembler import PromptContextAssembler, PromptContextRenderer
from ..common import TaskAgentLLMService


class ChatPromptService:
    """Owns prompt assembly and direct LLM invocation."""

    def __init__(
        self,
        *,
        agent_id: str,
        agent_type: str,
        llm_adapter=None,
        llm_pool=None,
        prompt_context_assembler: PromptContextAssembler,
        prompt_context_renderer: PromptContextRenderer,
        memory=None,
        other_memory=None,
    ) -> None:
        self._agent_id = agent_id
        self._agent_type = agent_type
        self._llm = llm_adapter
        self._llm_pool = llm_pool
        self._prompt_context_assembler = prompt_context_assembler
        self._prompt_context_renderer = prompt_context_renderer
        self._memory = memory
        self._other_memory = other_memory
        self._llm_service = TaskAgentLLMService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            scenario=LLMScenario.CORE,
            logger_name="chat",
        )

    async def build_prompt_context(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        task_category: str,
        tools: list[str],
        scenario: str = Scenario.CHAT,
    ) -> dict[str, Any]:
        retrieved_memory_payload = await self._build_retrieved_memory_payload(
            user_id=user_id,
            session_id=session_id,
            task_category=task_category,
        )
        return await self._prompt_context_assembler.assemble(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            scenario=scenario,
            task_category=task_category,
            user_id=user_id,
            self_memory=self._memory,
            other_memory=self._other_memory,
            tool_result={"tools": tools},
            retrieved_memory_payload=retrieved_memory_payload,
            state_transition_override=None,
            persona_name=self._memory.personality_name if self._memory else "default",
        )

    async def build_system_prompt(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        task_category: str,
        scenario: str = Scenario.CHAT,
    ) -> str:
        retrieved_memory_payload = await self._build_retrieved_memory_payload(
            user_id=user_id,
            session_id=session_id,
            task_category=task_category,
        )
        prompt_context = await self._prompt_context_assembler.assemble(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            scenario=scenario,
            task_category=task_category,
            user_id=user_id,
            self_memory=self._memory,
            other_memory=self._other_memory,
            tool_result={"tools": []},
            retrieved_memory_payload=retrieved_memory_payload,
            state_transition_override=None,
        )
        return self._prompt_context_renderer.render_system_prompt(prompt_context)

    def render_system_prompt(self, prompt_context: dict[str, Any]) -> str:
        return self._prompt_context_renderer.render_system_prompt(prompt_context)

    def build_recent_tool_errors_block(self, recent_tool_errors: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for item in recent_tool_errors[:3]:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name") or "unknown")
            error_code = str(item.get("error_code") or "UNKNOWN")
            error_message = str(item.get("error_message") or "").strip()
            config_path = str(item.get("config_path") or "").strip()
            next_action = str(item.get("next_action") or "").strip()
            line = f"- {tool_name}: {error_code}"
            if error_message:
                line += f" | {error_message}"
            if config_path:
                line += f" | config_path={config_path}"
            if next_action:
                line += f" | next_action={next_action}"
            lines.append(line)
        if not lines:
            return ""
        return "\n".join(
            [
                "# Recent Tool Errors",
                "Use these concrete failures as the source of truth for follow-up answers. Do not invent alternative config paths or switch tools unless the user explicitly asks to do so.",
                *lines,
            ]
        )

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        return await self._llm_service.call(
            system_prompt=system_prompt,
            messages=messages,
            disable_thinking=disable_thinking,
            temperature=0.7,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
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

    def build_aggregation_user_message(self, state, payload: dict[str, Any]) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False)
        research_requirements = self._build_research_aggregation_requirements(state.root_user_message)
        if self.prefers_chinese_response(state.root_user_message):
            lines = [
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
            return "\n".join(lines)
        lines = [
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
        return "\n".join(lines)

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

    async def _build_retrieved_memory_payload(
        self,
        *,
        user_id: str,
        session_id: str | None,
        task_category: str,
    ) -> dict[str, Any]:
        try:
            unified_memory = get_unified_memory()
        except Exception:
            unified_memory = None

        if unified_memory is None:
            return {
                "l0_workbench": [],
                "l2_entity_cards": [],
                "l3_reflection_memory": [],
                "l4_procedural_memory": [],
                "preference_memory": {},
            }

        retrieval = HybridRetrievalService(unified_memory)
        detail_payload = await retrieval.query(
            build_query(
                query=task_category,
                user_id=user_id,
                session_id=session_id,
                time_range={},
                query_mode="detail",
                source_filters=[],
                domain_filters=[],
                limit=5,
            )
        )
        summary_payload = await retrieval.query(
            build_query(
                query=task_category,
                user_id=user_id,
                session_id=session_id,
                time_range={},
                query_mode="summary",
                source_filters=[],
                domain_filters=[],
                limit=3,
            )
        )
        experience_payload = await retrieval.query(
            build_query(
                query=task_category,
                user_id=user_id,
                session_id=session_id,
                time_range={},
                query_mode="experience",
                source_filters=[],
                domain_filters=[],
                limit=3,
            )
        )
        return {
            "l0_workbench": detail_payload.l0_workbench,
            "l2_entity_cards": detail_payload.l2_entity_cards,
            "l3_reflection_memory": summary_payload.l3_reflections,
            "l4_procedural_memory": experience_payload.l4_procedures,
            "preference_memory": {},
        }
