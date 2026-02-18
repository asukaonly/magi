"""
Configuration introspection helpers for runtime setting paths.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union, get_args, get_origin

from pydantic import BaseModel, Field

from .models import AppConfig


class ConfigPathSpec(BaseModel):
    """Structured description for a configuration path."""
    path: str = Field(..., description="Dot-notated configuration path")
    type: str = Field(default="string", description="Primitive type name")
    description: str = Field(default="", description="Human-friendly description")


def _unwrap_optional(annotation: Any) -> Any:
    """Unwrap Optional[T] to T when possible."""
    origin = get_origin(annotation)
    if origin is Union:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _as_model(annotation: Any) -> Optional[type[BaseModel]]:
    """Return model class when annotation is a BaseModel subclass."""
    annotation = _unwrap_optional(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _dict_value_model(annotation: Any) -> Optional[type[BaseModel]]:
    """Return dict value model when annotation is Dict[str, Model]."""
    annotation = _unwrap_optional(annotation)
    origin = get_origin(annotation)
    if origin not in (dict, Dict):
        return None

    args = get_args(annotation)
    if len(args) != 2:
        return None

    return _as_model(args[1])


def _annotation_type_name(annotation: Any) -> str:
    """Map Python/Pydantic annotation to simple config type names."""
    annotation = _unwrap_optional(annotation)
    origin = get_origin(annotation)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return "string"
    if annotation is str:
        return "string"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    if origin in (list, List):
        return "array"
    if origin in (dict, Dict):
        return "object"
    if _as_model(annotation):
        return "object"
    return "string"


def _iter_model_paths(model_cls: type[BaseModel], prefix: str = "") -> List[ConfigPathSpec]:
    """Recursively flatten model fields into dot-notated path specs."""
    specs: List[ConfigPathSpec] = []

    for field_name, field_info in model_cls.model_fields.items():
        path = f"{prefix}.{field_name}" if prefix else field_name
        description = field_info.description or ""
        annotation = _unwrap_optional(field_info.annotation)

        nested_model = _as_model(annotation)
        if nested_model:
            specs.extend(_iter_model_paths(nested_model, path))
            continue

        dict_model = _dict_value_model(annotation)
        if dict_model:
            wildcard_path = f"{path}.{{key}}"
            specs.extend(_iter_model_paths(dict_model, wildcard_path))
            continue

        specs.append(
            ConfigPathSpec(
                path=path,
                type=_annotation_type_name(annotation),
                description=description,
            )
        )

    return specs


def list_app_config_specs(prefix: str = "app") -> List[ConfigPathSpec]:
    """
    Return flattened config specs from AppConfig model.

    Args:
        prefix: Path prefix added to every generated path.
    """
    specs = _iter_model_paths(AppConfig, "")
    if prefix:
        return [
            ConfigPathSpec(
                path=f"{prefix}.{item.path}",
                type=item.type,
                description=item.description,
            )
            for item in specs
        ]
    return specs
