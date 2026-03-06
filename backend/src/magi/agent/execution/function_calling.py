"""
Function Calling Executor - LLM native function calling support

Handles tool execution using LLM's native function calling capability:
1. Builds tools parameter in OpenAI/Claude format
2. Parses tool call responses from LLM
3. Executes tools (local or skill-based)
4. Supports continuous tool calling loop
"""
import inspect
import json
import logging
import os
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from dataclasses import dataclass

from ...llm.base import LLMAdapter
from ...llm.provider_bridge import LLMProviderBridge
from .function_calling_postprocessor import FunctionCallingPostprocessor
from ...utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

if TYPE_CHECKING:
    from ...tools.registry import ToolRegistry

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger('function_calling')


@dataclass
class ToolCall:
    """Represents a single tool call from LLM"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolCallResult:
    """Result of a tool call execution"""
    tool_call_id: str
    tool_name: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time: float = 0.0


class FunctionCallingExecutor:
    """
    Function Calling Executor

    Manages tool execution using LLM's native function calling.
    Supports continuous tool calling with multi-turn conversations.
    """

    max_ITERATIONS = 10  # Maximum tool calls in a single loop
    _EXPLORE_EXCLUDE_PATTERNS = [
        "node_modules",
        "dist",
        "build",
        ".git",
        ".venv",
        "__pycache__",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "bun.lockb",
    ]

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        tool_registry: "ToolRegistry",
        skill_executor=None,
        tool_result_callback=None,
        loop_event_callback=None,
    ):
        """
        initialize the executor

        Args:
            llm_adapter: LLM adapter
            tool_registry: Tool registry
            skill_executor: Optional skill executor for skill-based tools
        """
        self.llm = llm_adapter
        self.provider_bridge = LLMProviderBridge(llm_adapter)
        self.postprocessor = FunctionCallingPostprocessor()
        self.tool_registry = tool_registry
        self.skill_executor = skill_executor
        self.tool_result_callback = tool_result_callback
        self.loop_event_callback = loop_event_callback

    async def execute_with_tools(
        self,
        user_message: str,
        system_prompt: str,
        selected_tools: List[str],
        user_id: str,
        session_id: Optional[str] = None,
        conversation_history: List[Dict] = None,
        max_iterations: int = max_ITERATIONS,
        disable_thinking: bool = True,
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
        execution_workspace: Optional[str] = None,
    ) -> str:
        """
        Execute with continuous tool calling

        Args:
            user_message: User's message
            system_prompt: System prompt for LLM
            selected_tools: List of tool names to include
            user_id: User id for execution context
            conversation_history: Previous conversation
            max_iterations: Maximum tool call iterations

        Returns:
            Final response text
        """
        # Build messages
        messages = []
        if conversation_history:
            messages.extend(conversation_history[-10:])  # Last 10 messages
        messages.append({"role": "user", "content": user_message})

        # Build tools parameter
        tools = self._build_tools_parameter(selected_tools)

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            await self._emit_loop_event(
                {
                    "stage": "iteration_started",
                    "iteration": iteration,
                    "max_iterations": max_iterations,
                    "user_id": user_id,
                    "session_id": session_id,
                    "intent": intent,
                    "execution_agent_id": execution_agent_id,
                }
            )

            # Call LLM with tools
            response = await self._call_llm_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                disable_thinking=disable_thinking,
            )

            # Preserve assistant tool_call message for protocol-correct next turn
            assistant_message = response.get("assistant_message")
            if assistant_message:
                messages.append(assistant_message)

            # Check if LLM wants to call tools
            if response.get("tool_calls"):
                tool_calls = response["tool_calls"]
                logger.info(f"[FunctionCalling] Iteration {iteration}: {len(tool_calls)} tool(s) to execute")
                await self._emit_loop_event(
                    {
                        "stage": "llm_requested_tools",
                        "iteration": iteration,
                        "tool_names": [tool_call.name for tool_call in tool_calls],
                        "tool_count": len(tool_calls),
                        "user_id": user_id,
                        "session_id": session_id,
                        "intent": intent,
                        "execution_agent_id": execution_agent_id,
                    }
                )

                # Execute all tool calls
                tool_results = []
                for tool_call in tool_calls:
                    result = await self._execute_tool_call(
                        tool_call=tool_call,
                        user_id=user_id,
                        session_id=session_id,
                        intent=intent,
                        execution_agent_id=execution_agent_id,
                        execution_workspace=execution_workspace,
                    )
                    tool_results.append(result)
                    await self._emit_loop_event(
                        {
                            "stage": "tool_executed",
                            "iteration": iteration,
                            "tool_name": tool_call.name,
                            "tool_call_id": tool_call.id,
                            "success": result.success,
                            "error": result.error,
                            "execution_time": result.execution_time,
                            "user_id": user_id,
                            "session_id": session_id,
                            "intent": intent,
                            "execution_agent_id": execution_agent_id,
                        }
                    )
                    await self._emit_tool_result(
                        user_id=user_id,
                        session_id=session_id,
                        user_message=user_message,
                        intent=intent,
                        tool_call=tool_call,
                        result=result,
                    )

                    # Add tool result message
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            self.postprocessor.build_tool_message_payload(
                                tool_name=tool_call.name,
                                result=result,
                            )
                        ),
                    })

                # Check if all tools failed
                if all(not r.success for r in tool_results):
                    failed_details = []
                    for r in tool_results:
                        failed_details.append({
                            "tool_call_id": r.tool_call_id,
                            "tool_name": r.tool_name,
                            "error": r.error or "unknown error",
                            "execution_time": round(r.execution_time, 3),
                        })
                    logger.warning(
                        f"[FunctionCalling] All tools failed, stopping loop | details={failed_details}"
                    )
                    llm_logger.warning(
                        f"function_CallING_all_TOOLS_failED | iteration={iteration} | details={failed_details}"
                    )
                    await self._emit_loop_event(
                        {
                            "stage": "iteration_all_tools_failed",
                            "iteration": iteration,
                            "details": failed_details,
                            "user_id": user_id,
                            "session_id": session_id,
                            "intent": intent,
                            "execution_agent_id": execution_agent_id,
                        }
                    )
                    break

                # Continue loop for potential more tool calls

            elif response.get("content"):
                # LLM provided final response
                logger.info(f"[FunctionCalling] Final response received after {iteration} iteration(s)")
                await self._emit_loop_event(
                    {
                        "stage": "final_response",
                        "iteration": iteration,
                        "response_preview": str(response["content"])[:500],
                        "user_id": user_id,
                        "session_id": session_id,
                        "intent": intent,
                        "execution_agent_id": execution_agent_id,
                    }
                )
                return response["content"]

            else:
                # Unexpected response format
                logger.warning(f"[FunctionCalling] Unexpected response: {response}")
                break

        # Fallback: call LLM without tools for final response
        logger.info("[FunctionCalling] Reached max iterations, getting final response")
        await self._emit_loop_event(
            {
                "stage": "max_iterations_reached",
                "iteration": iteration,
                "max_iterations": max_iterations,
                "user_id": user_id,
                "session_id": session_id,
                "intent": intent,
                "execution_agent_id": execution_agent_id,
            }
        )
        final_response = await self._call_llm_without_tools(
            system_prompt=system_prompt,
            messages=messages,
            disable_thinking=disable_thinking,
        )

        # Some models return legacy <tool_call> blocks in fallback text-only responses.
        # Execute one bounded rescue pass so tool intents are not dropped silently.
        fallback_content = final_response.get("content", "")
        fallback_tool_calls = final_response.get("tool_calls") or []
        if fallback_tool_calls:
            logger.info(
                "[FunctionCalling] Fallback response returned %s tool call(s), executing rescue pass",
                len(fallback_tool_calls),
            )
            if fallback_content:
                messages.append({"role": "assistant", "content": fallback_content})
            for tool_call in fallback_tool_calls:
                result = await self._execute_tool_call(
                    tool_call=tool_call,
                    user_id=user_id,
                    session_id=session_id,
                    intent=intent,
                    execution_agent_id=execution_agent_id,
                    execution_workspace=execution_workspace,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            self.postprocessor.build_tool_message_payload(
                                tool_name=tool_call.name,
                                result=result,
                            )
                        ),
                    }
                )
            final_response = await self._call_llm_without_tools(
                system_prompt=system_prompt,
                messages=messages,
                disable_thinking=disable_thinking,
            )

        await self._emit_loop_event(
            {
                "stage": "fallback_final_response",
                "response_preview": str(final_response.get("content", ""))[:500],
                "user_id": user_id,
                "session_id": session_id,
                "intent": intent,
                "execution_agent_id": execution_agent_id,
            }
        )
        return final_response.get("content", "No response generated")

    async def _emit_tool_result(
        self,
        user_id: str,
        session_id: Optional[str],
        user_message: str,
        intent: str,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> None:
        """Emit tool execution result to external callback if provided."""
        if not self.tool_result_callback:
            return

        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
            "intent": intent,
            "tool_name": tool_call.name,
            "tool_call_id": tool_call.id,
            "arguments": tool_call.arguments,
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "execution_time": result.execution_time,
        }

        try:
            callback_result = self.tool_result_callback(payload)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as e:
            logger.warning(f"[FunctionCalling] Tool result callback failed: {e}")

    async def _emit_loop_event(self, payload: Dict[str, Any]) -> None:
        """Emit function-calling loop stage event to external callback if provided."""
        if not self.loop_event_callback:
            return
        try:
            callback_result = self.loop_event_callback(payload)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as e:
            logger.warning(f"[FunctionCalling] Loop event callback failed: {e}")

    def _build_tools_parameter(self, selected_tools: List[str]) -> List[Dict]:
        """
        Build tools parameter in OpenAI format

        Args:
            selected_tools: List of tool names to include

        Returns:
            List of tool definitions in OpenAI format
        """
        tools = []

        for tool_name in selected_tools:
            # Check if it's a skill
            if tool_name.startswith("/") or self.tool_registry.is_skill(tool_name.lstrip("/")):
                # Skills are handled differently - they provide instructions to LLM
                skill_name = tool_name.lstrip("/")
                skill = self.tool_registry._skills.get(skill_name)
                if skill and hasattr(skill, 'description'):
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": f"skill_{skill_name}",
                            "description": skill.description,
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "The user's request or task description for this skill to accomplish"
                                    }
                                },
                                "required": ["query"],
                            },
                        },
                    })
                continue

            # Regular tool
            tool_info = self.tool_registry.get_tool_info(tool_name)
            if not tool_info:
                continue

            tool_def = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_info.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }

            # Add parameters from schema
            params = tool_info.get("parameters", [])
            properties = {}
            required = []

            for param in params:
                param_name = param.get("name")
                if not param_name:
                    continue

                prop_def = {"type": param.get("type", "string")}
                if param.get("description"):
                    prop_def["description"] = param["description"]
                if param.get("enum"):
                    prop_def["enum"] = param["enum"]

                properties[param_name] = prop_def

                if param.get("required", False):
                    required.append(param_name)

            tool_def["function"]["parameters"]["properties"] = properties
            tool_def["function"]["parameters"]["required"] = required

            tools.append(tool_def)

        return tools

    async def _call_llm_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        tools: List[Dict],
        disable_thinking: bool = True,
    ) -> Dict[str, Any]:
        """
        Call LLM with tools parameter

        Returns dict with either:
        - content: str (text response)
        - tool_calls: List[ToolCall] (tool calls to execute)
        """
        import time
        import uuid

        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        model_name = self.llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=4096,
            temperature=0.7,
        )

        try:
            provider_response = await self.provider_bridge.chat_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=4096,
                temperature=0.7,
                disable_thinking=disable_thinking,
            )

            result: Dict[str, Any] = {"content": provider_response.content}
            if provider_response.assistant_message:
                result["assistant_message"] = provider_response.assistant_message
            if provider_response.tool_calls:
                result["tool_calls"] = [
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                    for tc in provider_response.tool_calls
                ]

            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=str(result),
                success=True,
                duration_ms=duration_ms,
            )
            return result

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )
            logger.error(f"[FunctionCalling] LLM call failed: {e}")
            raise

    async def _call_llm_without_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        disable_thinking: bool = True,
    ) -> Dict[str, Any]:
        """Call LLM without tools for final response"""
        import time
        import uuid

        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        model_name = self.llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=4096,
            temperature=0.7,
            fallback_reason="function_calling_final_response_without_tools",
        )

        try:
            provider_response = await self.provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=4096,
                temperature=0.7,
                disable_thinking=disable_thinking,
            )
            content = provider_response.content

            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=content,
                success=True,
                duration_ms=duration_ms,
                fallback_reason="function_calling_final_response_without_tools",
            )
            result: Dict[str, Any] = {"content": content}
            if provider_response.assistant_message:
                result["assistant_message"] = provider_response.assistant_message
            if provider_response.tool_calls:
                result["tool_calls"] = [
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                    for tc in provider_response.tool_calls
                ]
            return result
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                fallback_reason="function_calling_final_response_without_tools",
            )
            raise

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        user_id: str,
        session_id: Optional[str],
        intent: str,
        execution_agent_id: str,
        execution_workspace: Optional[str],
    ) -> ToolCallResult:
        """
        Execute a single tool call

        Args:
            tool_call: Tool call to execute
            user_id: User id for context

        Returns:
            ToolCallResult
        """
        import time
        start_time = time.time()

        tool_name = tool_call.name
        arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}

        logger.info(f"[FunctionCalling] Executing: {tool_name} with args: {arguments}")

        try:
            from ...tools.schema import ToolExecutionContext, ToolErrorCode

            # Check if it's a skill
            if tool_name.startswith("skill_"):
                skill_name = tool_name.replace("skill_", "")
                return await self._execute_skill(
                    skill_name=skill_name,
                    arguments=arguments,
                    user_id=user_id,
                )

            # Regular tool
            arguments, guardrail_error = self._apply_worker_explore_guardrails(
                intent=intent,
                tool_name=tool_name,
                arguments=arguments,
            )
            if guardrail_error:
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    success=False,
                    error=guardrail_error,
                    error_code=ToolErrorCode.INVALID_PARAMETERS.value,
                    execution_time=time.time() - start_time,
                )

            permissions = ["authenticated"]
            tool_info = self.tool_registry.get_tool_info(tool_name)
            if tool_info and tool_info.get("dangerous", False):
                permissions.append("dangerous_tools")

            context = ToolExecutionContext(
                agent_id=execution_agent_id,
                workspace=execution_workspace or os.getcwd(),
                env_vars={
                    "user_id": user_id,
                    "session_id": session_id or "",
                    "intent": intent,
                    "target_task_agent_type": "chat",
                    "target_task_agent_id": user_id,
                },
                permissions=permissions,
            )

            result = await self.tool_registry.execute(tool_name, arguments, context)
            if not result.success:
                logger.warning(
                    f"[FunctionCalling] Tool failed: {tool_name} | "
                    f"error={result.error} | code={result.error_code}"
                )

            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=result.success,
                data=result.data,
                error=result.error,
                error_code=getattr(result, "error_code", None),
                execution_time=time.time() - start_time,
            )

        except Exception as e:
            logger.error(f"[FunctionCalling] Tool execution error: {e}")
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    def _apply_worker_explore_guardrails(
        self,
        intent: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Optional[str]]:
        """Apply strict guardrails for explore workers to avoid exhaustive scans."""
        if intent != "worker_explore":
            return dict(arguments), None

        safe_args = dict(arguments)
        if tool_name == "glob":
            pattern = str(safe_args.get("pattern", "")).strip()
            if not pattern:
                return {}, "Explore worker guardrail: glob pattern is required."
            if pattern in {"*", "**/*", "**"}:
                # Downgrade broad scans to a bounded top-level listing instead of failing.
                safe_args["pattern"] = "*"
                safe_args["recursive"] = False
            if "recursive" not in safe_args:
                safe_args["recursive"] = "**" in pattern
            safe_args["max_results"] = self._bounded_max_results(safe_args.get("max_results"), cap=200)
            safe_args["exclude"] = self._merge_exclude_patterns(safe_args.get("exclude"))
            return safe_args, None

        if tool_name == "grep":
            file_glob = str(safe_args.get("glob", "*")).strip()
            path_value = str(safe_args.get("path", ".")).strip()
            if file_glob in {"*", "**/*", "**"} and path_value in {"", ".", "./"}:
                return {}, (
                    "Explore worker guardrail: root-wide grep is blocked. "
                    "Use a scoped glob like frontend/**/*.ts or backend/**/*.py."
                )
            if "recursive" not in safe_args:
                safe_args["recursive"] = "**" in file_glob
            safe_args["max_results"] = self._bounded_max_results(safe_args.get("max_results"), cap=200)
            safe_args["exclude"] = self._merge_exclude_patterns(safe_args.get("exclude"))
            return safe_args, None

        return safe_args, None

    def _bounded_max_results(self, value: Any, cap: int) -> int:
        """Parse max_results and keep it within [1, cap]."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = cap
        return max(1, min(parsed, cap))

    def _merge_exclude_patterns(self, extra: Any) -> List[str]:
        """Merge caller exclude patterns with explore defaults."""
        merged: List[str] = []
        if isinstance(extra, list):
            for item in extra:
                value = str(item).strip()
                if value and value not in merged:
                    merged.append(value)
        for pattern in self._EXPLORE_EXCLUDE_PATTERNS:
            if pattern not in merged:
                merged.append(pattern)
        return merged

    async def _execute_skill(
        self,
        skill_name: str,
        arguments: Dict[str, Any],
        user_id: str,
    ) -> ToolCallResult:
        """Execute a skill"""
        if not self.skill_executor:
            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=False,
                error="Skill executor not available",
            )

        import os
        skill_context = {
            "user_id": user_id,
            "session_id": f"session_{user_id}",
            "env_vars": {
                "user": os.getenv("user") or os.getenv("username") or "unknown",
                "HOME": os.path.expanduser("~"),
                "PWD": os.getcwd(),
            },
        }

        try:
            # Convert arguments dict to list for skill executor
            args_list = []
            if arguments:
                for key, value in arguments.items():
                    if isinstance(value, str):
                        args_list.append(value)
                    elif value is not None:
                        args_list.append(str(value))

            result = await self.skill_executor.execute(
                skill_name=skill_name,
                arguments=args_list,
                context=skill_context,
            )

            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=result.success,
                data=result.content,
                error=result.error,
            )

        except Exception as e:
            logger.error(f"[FunctionCalling] Skill execution error: {e}")
            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=False,
                error=str(e),
            )
