"""Unified API routes for durable L2 memory correction governance."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Query, status

from .....memory.event_contracts import generate_event_id
from .....memory.l2.corrections.models import CorrectionKind, CorrectionTargetKind
from .....memory.l2.corrections.repository import MemoryCorrectionRepository
from .....memory.l2.corrections.service import (
    MemoryCorrectionConflictError,
    MemoryCorrectionValidationError,
)
from ..dependencies import _resolve_unified_memory
from ..helpers import canonical_self_id, memory_t
from ..router import memory_router
from ..schemas import (
    MemoryCorrectionCommandResponse,
    MemoryCorrectionHistoryResponse,
    MemoryCorrectionRequest,
    MemoryCorrectionRevertRequest,
)


@memory_router.post(
    "/l2/corrections",
    response_model=MemoryCorrectionCommandResponse,
)
async def apply_memory_correction(
    body: MemoryCorrectionRequest,
) -> MemoryCorrectionCommandResponse:
    """Apply one assertion or relationship correction through the shared service."""
    unified_memory = _require_l2_memory()
    l2 = unified_memory.l2
    audit_event_id = (
        None if body.source_event_id is not None else generate_event_id(prefix="correction_audit")
    )
    actor_id = canonical_self_id(unified_memory)
    try:
        if body.target.kind == "assertion":
            replacement_value = _assertion_replacement_value(body)
            result = await l2.apply_assertion_correction(
                assertion_id=body.target.id,
                request_id=body.request_id,
                actor_id=actor_id,
                correction_kind=CorrectionKind(body.correction_kind),
                replacement_value=replacement_value,
                reason=body.reason,
                effective_at=body.effective_at,
                scope=body.scope,
                source_event_id=body.source_event_id,
                audit_event_id=audit_event_id,
                expected_updated_at=body.expected_updated_at,
            )
            current_claim_key = "current_assertion"
        else:
            result = await l2.apply_relationship_correction(
                triple_id=body.target.id,
                request_id=body.request_id,
                actor_id=actor_id,
                correction_kind=CorrectionKind(body.correction_kind),
                replacement=body.replacement,
                reason=body.reason,
                effective_at=body.effective_at,
                scope=body.scope,
                source_event_id=body.source_event_id,
                audit_event_id=audit_event_id,
                expected_updated_at=body.expected_updated_at,
            )
            current_claim_key = "current_relationship"
    except MemoryCorrectionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MemoryCorrectionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_validation_error_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t(
                "memory.errors.correction_target_not_found", "Correction target not found"
            ),
        )
    return await _command_response(l2, result, current_claim_key=current_claim_key)


@memory_router.get(
    "/l2/corrections",
    response_model=MemoryCorrectionHistoryResponse,
)
async def get_memory_correction_history(
    target_kind: Literal["assertion", "edge"] = Query(...),
    target_id: str = Query(..., min_length=1, max_length=200),
) -> MemoryCorrectionHistoryResponse:
    """Return immutable versions and correction records for one target."""
    unified_memory = _require_l2_memory()
    l2 = unified_memory.l2
    if target_kind == "assertion":
        assertion = await l2.get_tom_assertion(assertion_id=target_id)
        if assertion is None:
            raise _target_not_found()
        history = await l2.get_assertion_correction_history(slot_key=str(assertion["slot_key"]))
        versions = history["assertions"]
    else:
        relationship = await l2.get_relationship(triple_id=target_id)
        if relationship is None:
            raise _target_not_found()
        history = await l2.get_relationship_correction_history(triple_id=target_id)
        versions = history["versions"]
    return MemoryCorrectionHistoryResponse.model_validate(
        {
            "target": {"kind": target_kind, "id": target_id},
            "versions": versions,
            "corrections": history["corrections"],
        }
    )


@memory_router.post(
    "/l2/corrections/{correction_id}/revert",
    response_model=MemoryCorrectionCommandResponse,
)
async def revert_memory_correction(
    correction_id: str,
    body: MemoryCorrectionRevertRequest,
) -> MemoryCorrectionCommandResponse:
    """Revert the latest active correction for an assertion or relationship."""
    unified_memory = _require_l2_memory()
    l2 = unified_memory.l2
    correction = await MemoryCorrectionRepository(l2.db_path).get(correction_id)
    if correction is None:
        raise _target_not_found()
    try:
        if correction.target_kind == CorrectionTargetKind.ASSERTION:
            result = await l2.revert_assertion_correction(
                correction_id=correction_id,
                request_id=body.request_id,
                actor_id=canonical_self_id(unified_memory),
            )
            current_claim_key = "current_assertion"
        else:
            result = await l2.revert_relationship_correction(
                correction_id=correction_id,
                request_id=body.request_id,
                actor_id=canonical_self_id(unified_memory),
            )
            current_claim_key = "current_relationship"
    except MemoryCorrectionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MemoryCorrectionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_validation_error_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if result is None:
        raise _target_not_found()
    return await _command_response(l2, result, current_claim_key=current_claim_key)


def _require_l2_memory():
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    return unified_memory


def _assertion_replacement_value(body: MemoryCorrectionRequest) -> str | None:
    if body.replacement is None:
        return None
    value = body.replacement.get("value")
    if value is None or not str(value).strip():
        raise MemoryCorrectionValidationError(
            "Assertion replacement must contain a non-empty value"
        )
    return str(value).strip()


async def _command_response(
    l2,
    result: dict,
    *,
    current_claim_key: str,
) -> MemoryCorrectionCommandResponse:
    correction = result["correction"]
    derivation_state = await l2.get_memory_correction_derivation_state(
        str(correction["correction_id"])
    )
    return MemoryCorrectionCommandResponse.model_validate(
        {
            "correction": correction,
            "current_claim": result[current_claim_key],
            "subject_revision": result["subject_revision"],
            "derivation_state": derivation_state,
            "created": result["created"],
        }
    )


def _validation_error_detail(
    error: MemoryCorrectionValidationError,
) -> str | dict[str, str]:
    if not error.code:
        return str(error)
    return {"code": error.code, "message": str(error)}


def _target_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=memory_t("memory.errors.correction_target_not_found", "Correction target not found"),
    )


__all__ = [
    "apply_memory_correction",
    "get_memory_correction_history",
    "revert_memory_correction",
]
