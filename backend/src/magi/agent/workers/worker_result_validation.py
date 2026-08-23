"""Worker result validation helpers."""

from __future__ import annotations

import json
from typing import Any

from ...agent.orchestration import (
    PlannedSubtask,
    WorkerEvidence,
    WorkerFinding,
    WorkerResult,
)
from ..orchestration_models import MAX_WORKER_RESULT_RECORDS

_MAX_WORKER_RECORDS = MAX_WORKER_RESULT_RECORDS


class WorkerResultValidationMixin:
    """Validate structured JSON emitted by worker agents."""

    TYPE_PLAN: str
    TYPE_CODING: str
    TYPE_EXPLORE: str

    def _validate_worker_result(self, subagent_type: str, content: str) -> WorkerResult:
        stripped = str(content or "").strip()
        if not stripped:
            raise ValueError("Worker returned an empty response")
        parsed = self._parse_worker_json(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("Worker result must be a JSON object")
        required_keys = {
            "result_status",
            "summary",
            "findings",
            "evidence",
            "records",
            "gaps",
            "next_steps",
        }
        if subagent_type == self.TYPE_CODING:
            required_keys.update({"artifacts", "verification"})
        if not required_keys.issubset(set(parsed.keys())):
            raise ValueError("Worker result is missing required fields")
        raw_result_status = parsed.get("result_status")
        if not isinstance(raw_result_status, str):
            raise ValueError(
                "Worker result field 'result_status' must be success, partial, or failed"
            )
        result_status = raw_result_status.strip()
        if result_status not in {"success", "partial", "failed"}:
            raise ValueError(
                "Worker result field 'result_status' must be success, partial, or failed"
            )
        raw_summary = parsed.get("summary")
        if not isinstance(raw_summary, str) or not raw_summary.strip():
            raise ValueError("Worker result requires a non-empty string summary")
        list_fields = ["findings", "evidence", "gaps", "next_steps"]
        if subagent_type == self.TYPE_CODING:
            list_fields.extend(["artifacts", "verification"])
        for field_name in list_fields:
            if not isinstance(parsed.get(field_name), list):
                raise ValueError(f"Worker result field '{field_name}' must be a list")
        self._validate_raw_findings(parsed["findings"])
        self._validate_raw_evidence(parsed["evidence"])
        self._validate_string_items(parsed["gaps"], field_name="gaps")
        self._validate_string_items(parsed["next_steps"], field_name="next_steps")
        self._validate_records(parsed["records"])

        worker_result = WorkerResult.from_dict(parsed)
        if not worker_result.envelope_contract_valid:
            raise ValueError("Worker result contains malformed common fields")
        if not worker_result.string_lists_valid:
            raise ValueError(
                "Worker result fields 'gaps' and 'next_steps' must contain non-empty strings"
            )
        self._validate_findings(worker_result.findings, subagent_type=subagent_type)
        self._validate_evidence(worker_result.evidence)
        self._validate_string_items(worker_result.gaps, field_name="gaps")
        self._validate_string_items(worker_result.next_steps, field_name="next_steps")
        if subagent_type == self.TYPE_CODING:
            self._validate_coding_result(parsed, worker_result)
        if result_status == "failed":
            failure_reason = parsed.get("failure_reason")
            if not isinstance(failure_reason, str) or not failure_reason.strip():
                raise ValueError(
                    "Failed worker results must include a non-empty string failure_reason"
                )

        if subagent_type == self.TYPE_PLAN:
            subtasks = parsed.get("subtasks")
            if not isinstance(subtasks, list) or not subtasks:
                raise ValueError("Plan worker result must include non-empty subtasks")
            self._validate_plan_subtasks(subtasks)
            if not worker_result.plan_contract_valid:
                raise ValueError("Plan worker result contains malformed subtasks")
        return worker_result

    @staticmethod
    def _validate_coding_result(parsed: dict[str, Any], worker_result: WorkerResult) -> None:
        raw_artifacts = parsed["artifacts"]
        raw_verification = parsed["verification"]
        WorkerResultValidationMixin._validate_coding_artifacts(raw_artifacts)
        WorkerResultValidationMixin._validate_coding_verification(raw_verification)

        if worker_result.result_status not in {"success", "partial"}:
            return
        if not worker_result.artifacts:
            raise ValueError("Successful or partial coding results require at least one artifact")
        if not worker_result.verification:
            raise ValueError("Successful or partial coding results require verification evidence")
        if any(item.status != "passed" for item in worker_result.verification):
            raise ValueError(
                "Successful or partial coding results cannot contain failed verification"
            )
        if worker_result.result_status == "partial":
            WorkerResultValidationMixin._validate_coding_partial_fields(parsed)

    @staticmethod
    def _validate_coding_artifacts(raw_artifacts: list[Any]) -> None:
        valid_operations = {"created", "modified", "deleted"}
        for index, artifact in enumerate(raw_artifacts):
            if not isinstance(artifact, dict):
                raise ValueError(f"Coding artifact {index} must be a JSON object")
            path = artifact.get("path")
            operation = artifact.get("operation")
            if not isinstance(path, str) or not path.strip():
                raise ValueError(f"Coding artifact {index} requires a non-empty string path")
            if not isinstance(operation, str) or operation.strip() not in valid_operations:
                raise ValueError(
                    f"Coding artifact {index} requires a valid operation created, modified, or deleted"
                )

    @staticmethod
    def _validate_coding_verification(raw_verification: list[Any]) -> None:
        valid_statuses = {"passed", "failed"}
        for index, verification in enumerate(raw_verification):
            if not isinstance(verification, dict):
                raise ValueError(f"Coding verification {index} must be a JSON object")
            command = verification.get("command")
            status = verification.get("status")
            detail = verification.get("detail")
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"Coding verification {index} requires a non-empty string command")
            if not isinstance(status, str) or status.strip() not in valid_statuses:
                raise ValueError(f"Coding verification {index} requires status passed or failed")
            if not isinstance(detail, str) or not detail.strip():
                raise ValueError(f"Coding verification {index} requires a non-empty string detail")

    @staticmethod
    def _validate_coding_partial_fields(parsed: dict[str, Any]) -> None:
        for field_name in ("gaps", "next_steps"):
            values = parsed[field_name]
            if not values:
                raise ValueError(f"Partial coding results require non-empty {field_name}")
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(
                    f"Partial coding result field '{field_name}' requires non-empty strings"
                )

    @staticmethod
    def _parse_worker_json(content: str) -> Any:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for index, char in enumerate(content):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("Worker did not return valid JSON")

    def _validate_findings(self, findings: list[WorkerFinding], subagent_type: str) -> None:
        for item in findings:
            title = item.title.strip()
            detail = item.detail.strip()
            if not title or not detail:
                raise ValueError("Each worker finding requires non-empty title and detail")
            if subagent_type == self.TYPE_EXPLORE:
                path = (item.path or "").strip()
                why_it_matters = (item.why_it_matters or "").strip()
                if not path or not why_it_matters:
                    raise ValueError(
                        "Each CodeExplore worker finding requires non-empty path and why_it_matters"
                    )

    @staticmethod
    def _validate_raw_findings(findings: list[Any]) -> None:
        for index, item in enumerate(findings):
            if not isinstance(item, dict) or WorkerFinding.from_dict(item) is None:
                raise ValueError(
                    f"Worker finding {index} must be an object with valid string fields"
                )

    @staticmethod
    def _validate_evidence(evidence: list[WorkerEvidence]) -> None:
        for item in evidence:
            path = item.path.strip()
            detail = item.detail.strip()
            if not path or not detail:
                raise ValueError("Each worker evidence entry requires non-empty path and detail")

    @staticmethod
    def _validate_raw_evidence(evidence: list[Any]) -> None:
        for index, item in enumerate(evidence):
            if not isinstance(item, dict) or WorkerEvidence.from_dict(item) is None:
                raise ValueError(
                    f"Worker evidence {index} must be an object with valid string fields"
                )

    @staticmethod
    def _validate_string_items(values: list[str], field_name: str) -> None:
        for item in values:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"Worker result field '{field_name}' must contain non-empty strings"
                )

    @staticmethod
    def _validate_plan_subtasks(subtasks: list[Any]) -> None:
        for index, item in enumerate(subtasks):
            if not isinstance(item, dict) or PlannedSubtask.from_dict(item) is None:
                raise ValueError(
                    "Plan worker subtask "
                    f"{index} requires non-empty string description, subagent_type, and prompt"
                )

    @staticmethod
    def _validate_records(records: Any) -> None:
        if not isinstance(records, list):
            raise ValueError("Worker result field 'records' must be a list")
        if len(records) > _MAX_WORKER_RECORDS:
            raise ValueError(
                f"Worker result field 'records' cannot exceed {_MAX_WORKER_RECORDS} items"
            )
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"Worker result field 'records[{index}]' must be a JSON object")

    @staticmethod
    def _preview_worker_result(worker_result: WorkerResult, limit: int = 400) -> str:
        summary = str(worker_result.summary).strip()
        if summary:
            return summary[:limit]
        if worker_result.findings:
            first = worker_result.findings[0]
            detail = str(first.detail or first.title).strip()
            if detail:
                return detail[:limit]
        return ""
