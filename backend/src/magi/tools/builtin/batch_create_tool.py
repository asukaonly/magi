"""Agent tool: create a long-running, manifest-driven batch job."""
from __future__ import annotations

from typing import Any, Dict

from ...agent.batch import BatchJobStatus
from ...agent.batch.enumerator import enumerate_seed
from ...agent.batch.store import default_batch_store
from ..schema import (
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
                "Create a long-running batch job: seed a manifest from a seed_spec and "
                "process each item with the named handler skill. Use for large homogeneous "
                "batches (e.g. rename every video in a folder). Returns job_id + total_items."
            ),
            category="automation",
            parameters=[
                ToolParameter(
                    name="handler_ref", type=ParameterType.STRING, required=True,
                    description="Skill name whose prompt processes ONE item.",
                ),
                ToolParameter(
                    name="seed_spec", type=ParameterType.OBJECT, required=True,
                    description="Enumeration intent, e.g. {source:'fs', root, patterns, recursive}.",
                ),
                ToolParameter(
                    name="handler_config", type=ParameterType.OBJECT, required=False, default={},
                    description="Opaque handler params (engine does not interpret).",
                ),
                ToolParameter(
                    name="title", type=ParameterType.STRING, required=False, default="Batch job",
                    description="Human-readable job title.",
                ),
            ],
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        seed_spec = parameters.get("seed_spec") or {}
        try:
            inputs = enumerate_seed(seed_spec)
        except (ValueError, KeyError) as exc:
            return ToolResult(
                success=False, error=f"bad seed_spec: {exc}",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        store = default_batch_store()
        owner = context.env_vars.get("user_id") or "local_user"
        job = await store.create_job(
            title=parameters.get("title") or "Batch job",
            owner=owner,
            origin_session_id=context.env_vars.get("session_id") or "",
            origin_turn_id=context.env_vars.get("turn_id") or "",
            handler_ref=parameters["handler_ref"],
            handler_config=parameters.get("handler_config") or {},
            seed_spec=seed_spec,
        )
        await store.add_items(job.job_id, inputs)
        await store.set_job_status(job.job_id, BatchJobStatus.RUNNING)
        return ToolResult(
            success=True,
            data={"job_id": job.job_id, "total_items": len(inputs)},
        )
