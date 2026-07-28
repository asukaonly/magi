"""Shared runtime state for personality generation."""

from __future__ import annotations

import asyncio

from ....core.logger import get_logger
from .constants import PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS


logger = get_logger("magi.api.services.personality_generation")
_PERSONALITY_GENERATION_LLM_SEMAPHORE = asyncio.Semaphore(
    PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS
)
