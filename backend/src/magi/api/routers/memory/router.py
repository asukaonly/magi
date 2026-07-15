"""Shared router instance for memory API route modules."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .operation_boundary import memory_operation_boundary

memory_router = APIRouter(dependencies=[Depends(memory_operation_boundary)])
