"""
Function Calling Executor - LLM native function calling support

Handles tool execution using LLM's native function calling capability:
1. Builds tools parameter in OpenAI/Claude format
2. Parses tool call responses from LLM
3. Executes tools (local or skill-based)
4. Supports continuous tool calling loop
"""
import json
import logging
import inspect
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from .registry import ToolRegistry
from .schema import ToolExecutionContext
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

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

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        skill_executor=None,
        tool_result_callback=None,
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
        self.tool_registry = tool_registry
        self.skill_executor = skill_executor
        self.tool_result_callback = tool_result_callback

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

                # Execute all tool calls
                tool_results = []
                for tool_call in tool_calls:
                    result = await self._execute_tool_call(
                        tool_call=tool_call,
                        user_id=user_id,
                    )
                    tool_results.append(result)
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
                        "content": json.dumps({
                            "success": result.success,
                            "data": result.data,
                            "error": result.error,
                        }),
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
                    break

                # Continue loop for potential more tool calls

            elif response.get("content"):
                # LLM provided final response
                logger.info(f"[FunctionCalling] Final response received after {iteration} iteration(s)")
                return response["content"]

            else:
                # Unexpected response format
                logger.warning(f"[FunctionCalling] Unexpected response: {response}")
                break

        # Fallback: call LLM without tools for final response
        logger.info("[FunctionCalling] Reached max iterations, getting final response")
        final_response = await self._call_llm_without_tools(
            system_prompt=system_prompt,
            messages=messages,
            disable_thinking=disable_thinking,
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
            content = await self.provider_bridge.chat(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=4096,
                temperature=0.7,
                disable_thinking=disable_thinking,
            )

            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=content,
                success=True,
                duration_ms=duration_ms,
                fallback_reason="function_calling_final_response_without_tools",
            )
            return {"content": content}
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
        arguments = tool_call.arguments

        logger.info(f"[FunctionCalling] Executing: {tool_name} with args: {arguments}")

        try:
            # Check if it's a skill
            if tool_name.startswith("skill_"):
                skill_name = tool_name.replace("skill_", "")
                return await self._execute_skill(
                    skill_name=skill_name,
                    arguments=arguments,
                    user_id=user_id,
                )

            # Regular tool
            permissions = ["authenticated"]
            tool_info = self.tool_registry.get_tool_info(tool_name)
            if tool_info and tool_info.get("dangerous", False):
                permissions.append("dangerous_tools")

            context = ToolExecutionContext(
                agent_id="chat_agent",
                user_id=user_id,
                workspace="/tmp",
                env_vars={},
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
