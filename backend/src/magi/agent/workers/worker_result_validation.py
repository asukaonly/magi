"""Structured child-run result validation."""

from __future__ import annotations

import json
from typing import Any

from .child_preset import ChildRunPreset
from .child_result import (
    ChildArtifact,
    ChildEvidence,
    ChildFinding,
    ChildRunResult,
    ChildVerification,
    MAX_CHILD_RESULT_RECORDS,
)


class WorkerResultValidationMixin:
    """Validate the typed evidence envelope emitted by child runs."""

    def _validate_worker_result(
        self,
        preset: ChildRunPreset,
        content: str,
    ) -> ChildRunResult:
        parsed = self._parse_child_json(content)
        required = {
            "result_status",
            "summary",
            "findings",
            "evidence",
            "records",
            "gaps",
            "next_steps",
        }
        if preset is ChildRunPreset.WORKSPACE_WRITE:
            required.update({"artifacts", "verification"})
        if not required.issubset(parsed):
            raise ValueError("Child result is missing required fields")
        status = parsed.get("result_status")
        if not isinstance(status, str) or status not in {"success", "partial", "failed"}:
            raise ValueError("Child result_status must be success, partial, or failed")
        summary = parsed.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Child result requires a non-empty summary")
        for name in ("findings", "evidence", "records", "gaps", "next_steps"):
            if not isinstance(parsed.get(name), list):
                raise ValueError(f"Child result field '{name}' must be a list")
        if len(parsed["records"]) > MAX_CHILD_RESULT_RECORDS:
            raise ValueError(
                f"Child result records cannot exceed {MAX_CHILD_RESULT_RECORDS} items"
            )
        _validate_objects(parsed["findings"], ChildFinding.from_dict, "finding")
        _validate_objects(parsed["evidence"], ChildEvidence.from_dict, "evidence")
        if any(not isinstance(item, dict) for item in parsed["records"]):
            raise ValueError("Child result records must contain JSON objects")
        _validate_strings(parsed["gaps"], "gaps")
        _validate_strings(parsed["next_steps"], "next_steps")
        if status == "failed" and not str(parsed.get("failure_reason") or "").strip():
            raise ValueError("Failed child results require failure_reason")
        if preset is ChildRunPreset.WORKSPACE_WRITE:
            self._validate_workspace_write_result(parsed)
        return ChildRunResult.from_dict(parsed)

    @staticmethod
    def _validate_workspace_write_result(parsed: dict[str, Any]) -> None:
        artifacts = parsed.get("artifacts")
        verification = parsed.get("verification")
        if not isinstance(artifacts, list) or not isinstance(verification, list):
            raise ValueError("Workspace-write child result requires artifact and verification lists")
        _validate_objects(artifacts, ChildArtifact.from_dict, "artifact")
        _validate_objects(verification, ChildVerification.from_dict, "verification")
        if parsed["result_status"] not in {"success", "partial"}:
            return
        if not artifacts or not verification:
            raise ValueError(
                "Successful workspace-write child results require artifacts and verification"
            )
        result = ChildRunResult.from_dict(parsed)
        if any(item.status != "passed" for item in result.verification):
            raise ValueError("Successful workspace-write child results require passing verification")
        if result.result_status == "partial" and (not result.gaps or not result.next_steps):
            raise ValueError("Partial workspace-write results require gaps and next_steps")

    @staticmethod
    def _parse_child_json(content: str) -> dict[str, Any]:
        stripped = str(content or "").strip()
        if not stripped:
            raise ValueError("Child run returned an empty response")
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            value = None
            for index, char in enumerate(stripped):
                if char != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(stripped[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    value = candidate
                    break
        if not isinstance(value, dict):
            raise ValueError("Child result must be one JSON object")
        return value

    @staticmethod
    def _preview_worker_result(result: ChildRunResult, limit: int = 400) -> str:
        return result.summary[:limit]


def _validate_objects(values: list[Any], parser: Any, label: str) -> None:
    for index, value in enumerate(values):
        if parser(value) is None:
            raise ValueError(f"Child {label} {index} is invalid")


def _validate_strings(values: list[Any], field_name: str) -> None:
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"Child result {field_name} must contain non-empty strings")


__all__ = ["WorkerResultValidationMixin"]
