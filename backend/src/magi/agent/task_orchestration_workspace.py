"""Workspace resolution helpers for task orchestration."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any, Optional

from ..utils.runtime import get_default_chat_workspace_path
from ..core.logger import get_logger
from ..tools.schema import ToolExecutionContext
from ..utils.packaged_paths import get_repo_root
from magi.tools.capabilities import build_tool_capabilities

logger = get_logger(__name__)


class TaskOrchestrationWorkspaceMixin:
    """Build tool contexts and resolve workspace roots for orchestrations."""

    _runtime_key: str
    _parent_task_agent_type: str
    _session_workspace_provider: Any

    async def _build_agent_tool_context(
        self,
        user_id: str,
        session_id: str,
        workspace_root: Optional[str] = None,
        *,
        run_id: str | None = None,
        run_revision: int = 0,
        user_message_generation: int | None = None,
    ) -> ToolExecutionContext:
        parent_task_agent_id = self._resolve_parent_task_agent_id(user_id, session_id)
        resolved_workspace = str(workspace_root or "").strip()
        if not resolved_workspace:
            resolved_workspace = await self._default_workspace_root(
                user_id=user_id,
                session_id=session_id,
            )
        return ToolExecutionContext(
            agent_id=self._runtime_key,
            workspace=resolved_workspace,
            env_vars={
                "user_id": user_id,
                "session_id": session_id,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": parent_task_agent_id,
                "parent_task_agent_type": self._parent_task_agent_type,
                "parent_task_agent_id": parent_task_agent_id,
                "run_id": run_id or "",
                "run_revision": str(run_revision),
                "user_message_generation": (
                    "" if user_message_generation is None else str(user_message_generation)
                ),
            },
            permissions=["authenticated"],
            capabilities=build_tool_capabilities(),
        )

    def _resolve_parent_task_agent_id(self, user_id: str, session_id: str) -> str:
        if self._parent_task_agent_type == "chat" and str(session_id).strip():
            return session_id
        return user_id

    async def _resolve_workspace_root(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
    ) -> str:
        default_root = await self._default_workspace_root(
            user_id=user_id,
            session_id=session_id,
        )
        message = str(user_message or "").strip()
        if not message:
            logger.info(
                "task_orchestrator.workspace_resolved",
                parent_task_agent_type=self._parent_task_agent_type,
                session_id=session_id,
                workspace_root=default_root,
                source="default_empty_message",
            )
            return default_root

        explicit_candidates = self._extract_explicit_path_candidates(message, default_root)
        for candidate in explicit_candidates:
            normalized = self._normalize_existing_path(candidate)
            if normalized:
                logger.info(
                    "task_orchestrator.workspace_resolved",
                    parent_task_agent_type=self._parent_task_agent_type,
                    session_id=session_id,
                    workspace_root=normalized,
                    source="explicit_path_candidate",
                    candidate=candidate,
                )
                return normalized
        logger.info(
            "task_orchestrator.workspace_resolved",
            parent_task_agent_type=self._parent_task_agent_type,
            session_id=session_id,
            workspace_root=default_root,
            source="default_no_explicit_path",
        )
        return default_root

    async def _default_workspace_root(self, *, user_id: str, session_id: str) -> str:
        if self._parent_task_agent_type == "chat":
            session_workspace = await self._resolve_session_workspace_path(
                user_id=user_id,
                session_id=session_id,
            )
            if session_workspace:
                logger.info(
                    "task_orchestrator.default_workspace",
                    parent_task_agent_type=self._parent_task_agent_type,
                    session_id=session_id,
                    workspace_root=session_workspace,
                    source="session_workspace",
                )
                return session_workspace
            logger.warning(
                "task_orchestrator.default_workspace_missing_session_workspace",
                parent_task_agent_type=self._parent_task_agent_type,
                session_id=session_id,
            )
            return ""
        runtime_project_root = self._resolve_runtime_project_root()
        if runtime_project_root is not None:
            logger.info(
                "task_orchestrator.default_workspace",
                parent_task_agent_type=self._parent_task_agent_type,
                session_id=session_id,
                workspace_root=runtime_project_root,
                source="runtime_project_root",
            )
            return runtime_project_root
        fallback_root = get_default_chat_workspace_path()
        logger.info(
            "task_orchestrator.default_workspace",
            parent_task_agent_type=self._parent_task_agent_type,
            session_id=session_id,
            workspace_root=fallback_root,
            source="managed_chat_workspace_fallback",
        )
        return fallback_root

    async def _resolve_session_workspace_path(self, *, user_id: str, session_id: str) -> str | None:
        provider = self._session_workspace_provider
        if provider is None or not str(session_id or "").strip():
            return None
        try:
            resolved = provider(user_id=user_id, session_id=session_id)
            if inspect.isawaitable(resolved):
                resolved = await resolved
        except Exception:
            logger.warning(
                "task_orchestrator.session_workspace_provider_failed",
                parent_task_agent_type=self._parent_task_agent_type,
                session_id=session_id,
                exc_info=True,
            )
            return None
        normalized = str(resolved or "").strip() or None
        if normalized:
            logger.info(
                "task_orchestrator.session_workspace_provider_resolved",
                parent_task_agent_type=self._parent_task_agent_type,
                session_id=session_id,
                workspace_root=normalized,
            )
        return normalized

    def _resolve_runtime_project_root(self) -> str | None:
        candidate = get_repo_root()
        if any((candidate / marker).exists() for marker in ("backend", "frontend", "docs", ".git")):
            return str(candidate)
        return None

    def _extract_explicit_path_candidates(self, message: str, default_root: str) -> list[str]:
        candidates: list[str] = []
        tokens = message.replace("\n", " ").split()
        relative_prefixes = ("backend/", "frontend/", "docs/", "configs/", "scripts/")
        for token in tokens:
            cleaned = token.strip("`'\"()[]{}<>,，。；：!?")
            if not cleaned:
                continue
            if cleaned.startswith(("~/", "/")):
                candidates.append(cleaned)
                continue
            if cleaned.startswith(relative_prefixes):
                candidates.append(str(Path(default_root) / cleaned))
        return candidates

    def _normalize_existing_path(self, raw_path: str) -> Optional[str]:
        candidate = Path(os.path.expandvars(os.path.expanduser(raw_path))).resolve()
        if candidate.exists():
            return str(candidate if candidate.is_dir() else candidate.parent)
        return None
