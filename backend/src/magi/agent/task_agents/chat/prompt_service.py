"""Prompt construction and plain-chat LLM calls for chat task agents."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from ....config import get_config
from ....config.constants import DEFAULT_MAX_TOKENS
from ....core.logger import get_logger
from ....llm.provider_bridge import LLMProviderBridge
from ....memory.context_builder import Scenario
from ....memory.prompt_context_assembler import PromptContextAssembler, PromptContextRenderer
from ....utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

logger = get_logger(__name__)
llm_logger = get_llm_logger("chat")


class ChatPromptService:
    """Owns prompt assembly and direct LLM invocation."""

    def __init__(
        self,
        *,
        agent_id: str,
        agent_type: str,
        llm_adapter,
        prompt_context_assembler: PromptContextAssembler,
        prompt_context_renderer: PromptContextRenderer,
        memory=None,
        other_memory=None,
    ) -> None:
        self._agent_id = agent_id
        self._agent_type = agent_type
        self._llm = llm_adapter
        self._prompt_context_assembler = prompt_context_assembler
        self._prompt_context_renderer = prompt_context_renderer
        self._memory = memory
        self._other_memory = other_memory

    async def build_prompt_context(
        self,
        *,
        user_id: str,
        task_category: str,
        tools: list[str],
        scenario: str = Scenario.CHAT,
    ) -> dict[str, Any]:
        return await self._prompt_context_assembler.assemble(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            scenario=scenario,
            task_category=task_category,
            user_id=user_id,
            self_memory=self._memory,
            other_memory=self._other_memory,
            tool_result={"tools": tools},
            retrieved_memory_payload={
                "short_term_workbench": [],
                "reflection_memory_l5": [],
                "preference_memory": {},
            },
            state_transition_override=None,
            persona_name=self._memory.personality_name if self._memory else "default",
        )

    async def build_system_prompt(
        self,
        *,
        user_id: str,
        task_category: str,
        scenario: str = Scenario.CHAT,
    ) -> str:
        prompt_context = await self._prompt_context_assembler.assemble(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            scenario=scenario,
            task_category=task_category,
            user_id=user_id,
            self_memory=self._memory,
            other_memory=self._other_memory,
            tool_result={"tools": []},
            retrieved_memory_payload={},
            state_transition_override=None,
        )
        return self._prompt_context_renderer.render_system_prompt(prompt_context)

    def render_system_prompt(self, prompt_context: dict[str, Any]) -> str:
        return self._prompt_context_renderer.render_system_prompt(prompt_context)

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
    ) -> str:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        model_name = self._llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
        )

        try:
            provider_bridge = LLMProviderBridge(self._llm)
            provider_response = await provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=self._llm_max_tokens(),
                temperature=0.7,
                disable_thinking=disable_thinking,
            )
            response = provider_response.content
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=response,
                success=True,
                duration_ms=duration_ms,
                provider_metadata=provider_response.metadata,
            )
            if not response.strip():
                logger.warning(
                    "LLM returned empty content | request_id=%s model=%s disable_thinking=%s metadata=%s",
                    request_id,
                    model_name,
                    disable_thinking,
                    provider_response.metadata,
                )
            return response
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise

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
                    "result": item.worker_result,
                }
                for item in state.subtasks
                if item.status == "completed" and isinstance(item.worker_result, dict)
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
        if self.prefers_chinese_response(state.root_user_message):
            return "\n".join(
                [
                    f"用户原始请求：{state.root_user_message}",
                    "你已经拿到了内部子任务的结构化结果。现在请直接面向用户回答原始请求。",
                    "要求：",
                    "- 使用自然、正常的聊天语气，不要暴露子任务、worker、编排、JSON 或内部流程。",
                    "- 优先整合已经确认的信息，并在合适的时候引用关键文件路径作为依据。",
                    "- 对失败的部分，只需要简短说明哪些方面还没完全确认，不要把失败列表原样抄给用户。",
                    "- 如果已有信息不足以完整覆盖原问题，就先给出当前最可靠的结论，再明确缺口。",
                    "- 回复语言跟随用户。",
                    "",
                    f"内部结果(JSON): {payload_json}",
                ]
            )
        return "\n".join(
            [
                f"Original user request: {state.root_user_message}",
                "You already have the structured results from internal leaf tasks. Now answer the original request directly to the user.",
                "Requirements:",
                "- Respond in a natural conversational style and do not mention subtasks, workers, orchestration, JSON, or internal process details.",
                "- Prioritize confirmed information and cite key file paths naturally when they matter.",
                "- For failed areas, briefly mention what remains unconfirmed instead of dumping an internal failure list.",
                "- If the available evidence is incomplete, give the most reliable current conclusion first and then call out the remaining gaps.",
                "- Mirror the user's language.",
                "",
                f"Internal results (JSON): {payload_json}",
            ]
        )

    def build_explore_render_message(self, root_user_message: str, dossier: str) -> str:
        if self.prefers_chinese_response(root_user_message):
            return "\n".join(
                [
                    f"用户原始请求：{root_user_message}",
                    "下面是一份已经整理好的探索报告，请直接面向用户给出最终回答。",
                    "要求：",
                    "- 使用自然、正常的聊天语气，但允许多段或简短的小标题来提升清晰度。",
                    "- 以已经确认的信息为主，必要时自然引用关键文件路径。",
                    "- 对尚未确认的部分，简短说明边界和缺口，不要暴露内部流程。",
                    "",
                    dossier,
                ]
            )
        return "\n".join(
            [
                f"Original user request: {root_user_message}",
                "Below is a prepared exploration dossier. Answer the user directly based on it.",
                "Requirements:",
                "- Use a natural conversational tone, but you may use multiple paragraphs or short headings when clarity improves.",
                "- Lead with confirmed findings and cite important file paths naturally when they matter.",
                "- Briefly call out remaining gaps without exposing internal process details.",
                "",
                dossier,
            ]
        )

    def build_explore_render_fallback(self, root_user_message: str, dossier: str = "") -> str:
        if dossier.strip():
            return dossier.strip()
        if self.prefers_chinese_response(root_user_message):
            return "这次探索报告已经完成，但最终整理回答时没有拿到可用文本结果。"
        return "The exploration dossier completed, but the final rendering step did not return usable text."

    def build_aggregation_fallback(self, state) -> str:
        completed = [
            item for item in state.subtasks
            if item.status == "completed" and isinstance(item.worker_result, dict)
        ]
        failed = [item for item in state.subtasks if item.status == "failed"]
        if self.prefers_chinese_response(state.root_user_message):
            lines = ["我先基于目前已经确认的结果给你一个可用的结论。", ""]
            if completed:
                lines.append("目前已经确认的部分：")
                for item in completed:
                    summary = str(item.worker_result.get("summary", "")).strip()
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
                summary = str(item.worker_result.get("summary", "")).strip()
                lines.append(f"- {summary or 'Completed with structured findings.'}")
        if failed:
            lines.append("")
            lines.append("These areas are still not fully confirmed because the underlying worker run failed:")
            for item in failed:
                lines.append(f"- {item.description}")
        return "\n".join(lines).strip()

    def prefers_chinese_response(self, text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _llm_max_tokens(self) -> int:
        try:
            return int(get_config().llm.max_tokens)
        except Exception:
            return DEFAULT_MAX_TOKENS
