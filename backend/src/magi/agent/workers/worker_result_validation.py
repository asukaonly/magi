"""Worker result validation helpers."""

from __future__ import annotations

import json
from typing import Any

from ...agent.orchestration import WorkerEvidence, WorkerFinding, WorkerResult

_MAX_WORKER_RECORDS = 500


class WorkerResultValidationMixin:
    """Validate structured JSON emitted by worker agents."""

    TYPE_PLAN: str
    TYPE_CODING: str
    TYPE_EXPLORE: str

    def _validate_worker_result(self, subagent_type: str, content: str) -> WorkerResult:
        stripped = str(content or "").strip()
        if not stripped:
            raise ValueError("Worker returned an empty response")
        if subagent_type == self.TYPE_CODING:
            return WorkerResult(summary=stripped, result_status="success")
        parsed = self._parse_worker_json(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("Worker result must be a JSON object")
        required_keys = {"result_status", "summary", "findings", "evidence", "gaps", "next_steps"}
        if not required_keys.issubset(set(parsed.keys())):
            raise ValueError("Worker result is missing required fields")
        result_status = str(parsed.get("result_status", "")).strip()
        if result_status not in {"success", "partial", "failed"}:
            raise ValueError(
                "Worker result field 'result_status' must be success, partial, or failed"
            )
        for field_name in ("findings", "evidence", "gaps", "next_steps"):
            if not isinstance(parsed.get(field_name), list):
                raise ValueError(f"Worker result field '{field_name}' must be a list")
        self._validate_records(parsed.get("records", []))

        worker_result = WorkerResult.from_dict(parsed)
        if not worker_result.summary:
            raise ValueError("Worker result requires a non-empty summary")
        self._validate_findings(worker_result.findings, subagent_type=subagent_type)
        self._validate_evidence(worker_result.evidence)
        self._validate_string_items(worker_result.gaps, field_name="gaps")
        self._validate_string_items(worker_result.next_steps, field_name="next_steps")
        if result_status == "failed" and not str(parsed.get("failure_reason") or "").strip():
            raise ValueError("Failed worker results must include failure_reason")

        if subagent_type == self.TYPE_PLAN:
            subtasks = parsed.get("subtasks")
            if not isinstance(subtasks, list) or not subtasks:
                raise ValueError("Plan worker result must include non-empty subtasks")
            if not worker_result.subtasks:
                raise ValueError(
                    "Plan worker subtasks require description, subagent_type, and prompt"
                )
        return worker_result

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
    def _validate_evidence(evidence: list[WorkerEvidence]) -> None:
        for item in evidence:
            path = item.path.strip()
            detail = item.detail.strip()
            if not path or not detail:
                raise ValueError("Each worker evidence entry requires non-empty path and detail")

    @staticmethod
    def _validate_string_items(values: list[str], field_name: str) -> None:
        for item in values:
            if not str(item).strip():
                raise ValueError(f"Worker result field '{field_name}' cannot contain empty items")

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
                raise ValueError(
                    f"Worker result field 'records[{index}]' must be a JSON object"
                )

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
