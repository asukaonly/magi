"""Magi IPC subsystem — NDJSON channel between Rust gateway and Python worker."""

from magi.ipc.server import IpcServer

__all__ = ["IpcServer"]
