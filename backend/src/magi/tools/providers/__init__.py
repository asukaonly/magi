"""
Provider abstraction for multi-provider tools.

This module provides the base classes for implementing service providers
that can be used by tools supporting multiple backends.
"""
from .base import Provider, ProviderConfig

__all__ = ["Provider", "ProviderConfig"]
