"""Committed cleanup work shared by the application and persistence ports."""

from dataclasses import dataclass, field
from typing import Protocol, Literal
from ..core.code_agent_artifacts import (
    CodeAgentDelegationReference,
    WorkspaceSessionArtifactReference,
)

from magi_plugin_sdk.storage_models.chat_cleanup import (
    ChatCleanupPlan,
    ChatAssetInventory,
    ChatCleanupTransactions,
)
