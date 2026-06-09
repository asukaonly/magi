"""Re-export shim — errors now live in the SDK.

All host code (factory.py, providers/, tests) that does
    from .errors import ImageGenProviderError, ...
continues to work unchanged, and class identity is preserved.
"""

from __future__ import annotations

from magi_plugin_sdk.image_generation.errors import (  # noqa: F401
    ImageGenAuthError,
    ImageGenContentFilteredError,
    ImageGenInvalidParameterError,
    ImageGenProviderError,
    ImageGenRateLimitError,
    ImageGenTimeoutError,
)
