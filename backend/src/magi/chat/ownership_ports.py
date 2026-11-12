"""Narrow persistence contracts for dependencies and private artifact ownership."""

from dataclasses import dataclass
from typing import Protocol

from ..core.code_agent_artifacts import CodeAgentDelegationReference

from magi_plugin_sdk.storage_models.chat_ownership import (
    ChatConsumedEventsRepository,
    ChatArtifactRepository,
    ChatAssetOwnership,
    ChatAssetOwnershipRepository,
)
