"""Public API for LLM-backed personality configuration generation."""

from ..personality_generation_prompts import (
    PERSONA_GENERATION_SHARED_DIRECTIVES,
)
from .constants import (
    GENERATION_STAGE_DEFINITIONS,
    PERSONALITY_GENERATION_JOB_TTL_SECONDS,
    PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS,
    REQUIRED_REGISTERS,
)
from .contracts import (
    PersonalityGenerationJob,
    PersonalityGenerationResult,
)
from .jobs import (
    get_personality_generation_job,
    personality_generation_user_content_clear_boundary,
    start_personality_generation_job,
)
from .normalization import normalize_generated_personality_payload
from .pipeline import (
    generate_personality_config,
    generate_personality_config_result,
)


__all__ = [
    "GENERATION_STAGE_DEFINITIONS",
    "PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS",
    "PERSONALITY_GENERATION_JOB_TTL_SECONDS",
    "PERSONA_GENERATION_SHARED_DIRECTIVES",
    "PersonalityGenerationJob",
    "PersonalityGenerationResult",
    "REQUIRED_REGISTERS",
    "get_personality_generation_job",
    "generate_personality_config",
    "generate_personality_config_result",
    "normalize_generated_personality_payload",
    "personality_generation_user_content_clear_boundary",
    "start_personality_generation_job",
]
