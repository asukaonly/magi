"""Stable identities and local resolution for memory context scopes."""

from .catalog import ContextCatalog
from .identity import (
    context_id_for_builtin,
    context_id_for_legacy_value,
    context_id_for_workspace,
    normalize_alias,
    workspace_binding_id,
)
from .models import (
    ContextCondition,
    ContextDimension,
    ContextOption,
    ContextResolutionSignals,
    ContextScopeError,
    canonical_context_scope,
    merge_context_scopes,
    normalize_context_scope,
)
from .resolver import ContextScopeResolver

__all__ = [
    "ContextCatalog",
    "ContextCondition",
    "ContextDimension",
    "ContextOption",
    "ContextResolutionSignals",
    "ContextScopeError",
    "ContextScopeResolver",
    "canonical_context_scope",
    "context_id_for_builtin",
    "context_id_for_legacy_value",
    "context_id_for_workspace",
    "merge_context_scopes",
    "normalize_alias",
    "normalize_context_scope",
    "workspace_binding_id",
]
