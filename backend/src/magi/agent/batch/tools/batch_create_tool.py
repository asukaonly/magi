"""Agent tool: create a long-running, manifest-driven batch job."""
from __future__ import annotations

from typing import Any, Dict

from .. import BatchJobStatus
from ..enumerator import enumerate_seed
from ..store import default_batch_store
from ..tool_selection import BatchToolSelectionError, resolve_batch_tool_names

# agent.batch.tools is host runtime-control code (L12). Import the Tool base +
# schema helpers straight from the SDK (downward, legal), mirroring how
# magi.agent.runtime_tools.agent_tool imports its contracts.
from magi_plugin_sdk import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class BatchCreateTool(Tool):
    """Seed a manifest from a seed_spec and start a batch job. Returns job_id."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="batch_create",
            description=(
                "Create a long-running batch job over MANY homogeneous items — e.g. "
                "rename every video in a folder, transcode a directory, batch-verify a "
                "list. **Use this instead of processing items one-by-one with native "
                "shell/file tools whenever there are many similar items**: first glob the target; if "
                "it's more than ~30 items, use batch_create. (One-by-one hits the per-turn "
                "iteration cap, can't resume on crash, and re-prompts for permission each "
                "time.) Provide how to process ONE item via `handler_prompt` (inline "
                "instruction — easiest) OR `handler_ref` (a skill name). Seeds a manifest "
                "from `seed_spec` and drives each item through that handler. "
                "Returns job_id + total_items."
            ),
            category="automation",
            effect_class="external_write",
            parameters=[
                ToolParameter(
                    name="seed_spec", type=ParameterType.OBJECT, required=True,
                    description="Enumeration intent, e.g. {source:'fs', root, patterns:['*.mkv','*.mp4'], recursive}.",
                ),
                ToolParameter(
                    name="handler_prompt", type=ParameterType.STRING, required=False,
                    description=(
                        "Inline instruction for processing ONE item (use this for quick/"
                        "one-off jobs instead of writing a skill). e.g. 'Look up the movie "
                        "for this file via web search, rename it to \"Title (Year) - Genre "
                        "- Cast\"; if unsure, mark needs_review.'"
                    ),
                ),
                ToolParameter(
                    name="handler_ref", type=ParameterType.STRING, required=False, default="inline",
                    description="Skill name to process one item. Defaults to 'inline' when handler_prompt is given.",
                ),
                ToolParameter(
                    name="handler_config", type=ParameterType.OBJECT, required=False, default={},
                    description=(
                        "Handler options, e.g. {dry_run:true}. An optional `tools` array "
                        "overrides the live registered tool set; unknown and non-native "
                        "shell names are rejected."
                    ),
                ),
                ToolParameter(
                    name="title", type=ParameterType.STRING, required=False, default="Batch job",
                    description="Human-readable job title.",
                ),
                ToolParameter(
                    name="concurrency", type=ParameterType.INTEGER, required=False, default=3,
                    description=(
                        "How many items to process in parallel (independent background "
                        "runs). Default 3; capped by the global background concurrency, "
                        "always leaving one slot for other tasks."
                    ),
                ),
            ],
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        seed_spec = parameters.get("seed_spec") or {}
        handler_prompt = parameters.get("handler_prompt")
        handler_ref = parameters.get("handler_ref") or "inline"
        if not handler_prompt and handler_ref == "inline":
            return ToolResult(
                success=False,
                error="provide handler_prompt (inline instruction) or handler_ref (skill name)",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        handler_config = dict(parameters.get("handler_config") or {})
        registry = getattr(self, "_tool_registry_ref", None)
        try:
            handler_config["tools"] = resolve_batch_tool_names(
                handler_config.get("tools"),
                registry=registry,
            )
        except BatchToolSelectionError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        try:
            inputs = enumerate_seed(seed_spec)
        except (ValueError, KeyError) as exc:
            return ToolResult(
                success=False, error=f"bad seed_spec: {exc}",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        if handler_prompt:
            handler_config["prompt"] = handler_prompt  # inline handler; no skill needed

        store = default_batch_store()
        owner = context.env_vars.get("user_id") or "local_user"
        job = await store.create_job(
            title=parameters.get("title") or "Batch job",
            owner=owner,
            origin_session_id=context.env_vars.get("session_id") or "",
            origin_turn_id=context.env_vars.get("turn_id") or "",
            handler_ref=handler_ref,
            handler_config=handler_config,
            seed_spec=seed_spec,
            concurrency=int(parameters.get("concurrency") or 3),
        )
        # inputs is a lazy iterator; add_items consumes it and returns the count.
        total_items = await store.add_items(job.job_id, inputs)
        await store.set_job_status(job.job_id, BatchJobStatus.RUNNING)

        # W1: fire the first batch through the real BackgroundManager. Surface
        # the outcome in the result so failures are visible (not silently swallowed).
        kickoff = "skipped"
        try:
            from ...background.provider import resolve_background_task_manager
            from ..driver import BatchDriver

            started = await BatchDriver(
                resolve_background_task_manager(),
                tool_registry=registry,
            ).kickoff(job.job_id)
            kickoff = f"started {started} runs"
        except Exception as exc:  # noqa: BLE001 - report kickoff failure, don't hide it
            kickoff = f"kickoff failed: {type(exc).__name__}: {exc}"
        return ToolResult(
            success=True,
            data={"job_id": job.job_id, "total_items": total_items, "kickoff": kickoff},
        )
