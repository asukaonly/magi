"""Unified API routes for durable L2 memory correction governance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Literal

from fastapi import HTTPException, Query, status

from .....memory.context_scope import ContextCatalog, ContextScopeError
from .....memory.event_contracts import generate_event_id
from .....memory.l2.corrections.models import CorrectionKind, CorrectionTargetKind
from .....memory.l2.corrections.repository import MemoryCorrectionRepository
from .....memory.l2.corrections.service import (
    MemoryCorrectionConflictError,
    MemoryCorrectionValidationError,
)
from .correction_history import (
    correction_history_slot_key,
    decorate_correction_records,
    prepare_correction_history,
    public_current_claim,
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
    requested_scope = body.scope.model_dump() if body.scope is not None else None
    repository = MemoryCorrectionRepository(l2.db_path)
    existing_request = await repository.get_by_request_id(body.request_id)
    if existing_request is None:
        try:
            scope = await ContextCatalog(l2.db_path).validate_correction_scope(requested_scope)
        except ContextScopeError as exc:
            existing_request = await repository.get_by_request_id(body.request_id)
            if existing_request is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": exc.code, "message": str(exc)},
                ) from exc
            scope = requested_scope or {}
    else:
        scope = requested_scope or {}
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
                scope=scope or None,
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
                scope=scope or None,
                source_event_id=body.source_event_id,
                audit_event_id=audit_event_id,
                expected_updated_at=body.expected_updated_at,
            )
            current_claim_key = "current_relationship"
    except MemoryCorrectionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_error_detail(exc),
        ) from exc
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
        slot_key = (
            str(assertion["slot_key"])
            if assertion is not None
            else await correction_history_slot_key(
                l2.db_path,
                target_kind=CorrectionTargetKind.ASSERTION,
                target_id=target_id,
            )
        )
        if not slot_key:
            raise _target_not_found()
        history = await l2.get_assertion_correction_history(slot_key=slot_key)
        versions = history["assertions"]
    else:
        relationship = await l2.get_relationship(triple_id=target_id)
        if relationship is None:
            slot_key = await correction_history_slot_key(
                l2.db_path,
                target_kind=CorrectionTargetKind.EDGE,
                target_id=target_id,
            )
            if not slot_key:
                raise _target_not_found()
        history = await l2.get_relationship_correction_history(triple_id=target_id)
        versions = history["versions"]
    versions, correction_records = await prepare_correction_history(
        l2.db_path,
        target_kind=CorrectionTargetKind(target_kind),
        versions=versions,
        corrections=history["corrections"],
    )
    context_labels = await ContextCatalog(l2.db_path).get_context_labels(
        _referenced_context_ids(versions, correction_records)
    )
    return MemoryCorrectionHistoryResponse.model_validate(
        {
            "target": {"kind": target_kind, "id": target_id},
            "versions": versions,
            "corrections": correction_records,
            "context_labels": context_labels,
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_error_detail(exc),
        ) from exc
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
    unknown_fields = set(body.replacement) - {"value"}
    if unknown_fields:
        unknown = ", ".join(sorted(str(item) for item in unknown_fields))
        raise MemoryCorrectionValidationError(
            f"Unsupported assertion replacement fields: {unknown}"
        )
    value = body.replacement.get("value")
    if value is None:
        return None
    return str(value).strip()


def _conflict_error_detail(exc: MemoryCorrectionConflictError) -> str | dict[str, str]:
    if exc.code is None:
        return str(exc)
    return {"code": exc.code, "message": str(exc)}


async def _command_response(
    l2,
    result: dict,
    *,
    current_claim_key: str,
) -> MemoryCorrectionCommandResponse:
    correction = result["correction"]
    decorated = await decorate_correction_records(l2.db_path, [correction])
    current_claim = (
        None
        if decorated[0]["content_redacted"]
        else public_current_claim(
            CorrectionTargetKind(
                getattr(correction["target_kind"], "value", correction["target_kind"])
            ),
            result[current_claim_key],
        )
    )
    derivation_state = await l2.get_memory_correction_derivation_state(
        str(correction["correction_id"])
    )
    return MemoryCorrectionCommandResponse.model_validate(
        {
            "correction": decorated[0],
            "current_claim": current_claim,
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


def _referenced_context_ids(*values: object) -> set[str]:
    found: set[str] = set()

    def visit(value: object) -> None:
        if is_dataclass(value) and not isinstance(value, type):
            visit(asdict(value))
            return
        if isinstance(value, Mapping):
            context_id = value.get("context_id")
            if isinstance(context_id, str) and context_id.strip():
                found.add(context_id.strip())
            for nested in value.values():
                visit(nested)
            return
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for nested in value:
                visit(nested)

    for value in values:
        visit(value)
    return found


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
