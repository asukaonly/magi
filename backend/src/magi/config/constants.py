"""LLM Token related constant definitions"""

# Default maximum token count for primary LLM
DEFAULT_MAX_TOKENS = 4096

# Skills sub-agent token limit
DEFAULT_SKILL_MAX_TOKENS = 4000

# Maximum tokens for tool responses
DEFAULT_TOOL_RESPONSE_TOKENS = 2000

# Thinking output related
DEFAULT_THINKING_TOKENS = 1024
MIN_THINKING_TOKENS = 300

# Minimum value constraints
MIN_MAX_TOKENS = 1

# Internal marker the renderer inserts between the byte-stable head of the
# system prompt (identity/boundary/tool-catalog) and its per-turn dynamic tail
# (persona/memory/runtime). The provider bridge splits on it to place a
# prompt-cache breakpoint on the stable head, then strips it before sending so
# it never reaches the model. See the unified prompt-cache layer (#110).
SYSTEM_PROMPT_CACHE_BOUNDARY = "<!--MAGI_CACHE_BOUNDARY-->"
