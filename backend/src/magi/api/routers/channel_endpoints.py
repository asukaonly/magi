"""Product API for explicit destination discovery and selection."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from magi_plugin_sdk.endpoints import EndpointRef

from ...delivery.outbox import DeliveryStatus

from ..runtime_dependencies import get_api_runtime_dependencies

router = APIRouter()


class EndpointView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: EndpointRef
    label: str
    capabilities: list[Literal["message", "audio", "control"]]
    available: bool


class EndpointListResponse(BaseModel):
    endpoints: list[EndpointView]


class DeliveryPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[EndpointRef] = Field(max_length=32)


def _catalog():
    module = get_api_runtime_dependencies().channels_module
    catalog = module.endpoint_catalog if module is not None else None
    if catalog is None:
        raise HTTPException(503, "Channel endpoints are not ready")
    return catalog


@router.get("/endpoints", response_model=EndpointListResponse)
async def list_endpoints() -> EndpointListResponse:
    return EndpointListResponse(endpoints=await _catalog().list_endpoints())


@router.get("/delivery-preferences", response_model=DeliveryPreferences)
async def get_delivery_preferences() -> DeliveryPreferences:
    return DeliveryPreferences(targets=_catalog().delivery_preferences())


@router.put("/delivery-preferences", response_model=DeliveryPreferences)
async def set_delivery_preferences(payload: DeliveryPreferences) -> DeliveryPreferences:
    try:
        await _catalog().set_delivery_preferences([target.to_dict() for target in payload.targets])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return payload


class DeliveryStatusResponse(BaseModel):
    deliveries: list[DeliveryStatus]


@router.get("/delivery-status", response_model=DeliveryStatusResponse)
async def get_delivery_status() -> DeliveryStatusResponse:
    try:
        return DeliveryStatusResponse(deliveries=await _catalog().delivery_status())
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
