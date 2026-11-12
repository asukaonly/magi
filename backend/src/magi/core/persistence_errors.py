"""Canonical failures shared by storage providers and their consumers."""

from magi_plugin_sdk.persistence_errors import PersistenceConflictError, PersistenceUnavailableError

__all__ = ["PersistenceConflictError", "PersistenceUnavailableError"]
