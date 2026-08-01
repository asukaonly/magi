"""Startup ordering for interrupted destructive chat work."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_startup_restores_barriers_before_recovering_chat_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.chat import forgetting as forgetting_module
    from magi.chat import read_service as read_service_module
    from magi.chat import runtime_forgetting as runtime_forgetting_module
    from magi.chat.lifecycle import ChatForgettingRecoveryModule

    calls: list[str] = []

    class _ReadService:
        async def abackfill_cleared_chat_scopes(
            self,
            session_ids: list[str],
            message_scopes: list[tuple[str, str]],
        ) -> dict[str, int]:
            calls.append(f"backfill:{session_ids}:{message_scopes}")
            return {
                "sessions": len(session_ids),
                "messages": len(message_scopes),
            }

        async def arecover_interrupted_global_clear(self) -> bool:
            calls.append("recover-global-clear")
            return True

    class _Memory:
        l0 = object()

        def __init__(self) -> None:
            self.pages = 0

        async def list_completed_chat_forget_operations(self, **_kwargs):
            calls.append("list-completed-forgets")
            self.pages += 1
            if self.pages > 1:
                return []
            selector = type(
                "_Selector",
                (),
                {
                    "kind": "chat_history",
                    "payload": {
                        "session_id": "session-1",
                        "surface_message_ids": ["message-1", "message-2"],
                    },
                },
            )()
            return [
                type(
                    "_Operation",
                    (),
                    {
                        "operation_id": "forget-1",
                        "created_at": 1.0,
                        "selector": selector,
                    },
                )()
            ]

    class _Recovery:
        def __init__(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        async def recover_pending(self) -> dict[str, int]:
            calls.append("recover-forget-surfaces")
            return {
                "intents_found": 0,
                "intents_activated": 0,
                "surfaces_found": 0,
                "surfaces_completed": 0,
            }

    monkeypatch.setattr(
        read_service_module,
        "get_chat_read_service",
        lambda: _ReadService(),
    )
    monkeypatch.setattr(
        forgetting_module,
        "ChatForgettingRecoveryService",
        _Recovery,
    )
    monkeypatch.setattr(
        runtime_forgetting_module,
        "ChatRuntimeForgettingCoordinator",
        lambda **_kwargs: object(),
    )

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = type(
        "_RuntimePaths",
        (),
        {"cache_dir": tmp_path / "cache"},
    )()
    context.chat.store = object()
    context.memory.unified_memory = _Memory()
    context.runtime_commands.runtime_command_queue = object()
    portrait_dir = tmp_path / "cache" / "portrait"
    portrait_dir.mkdir(parents=True)
    portrait_cache = portrait_dir / "cache.json"
    portrait_temp = portrait_dir / ".portrait-cache-orphan.json"
    portrait_cache.write_text("private portrait", encoding="utf-8")
    portrait_temp.write_text("private temp portrait", encoding="utf-8")

    await ChatForgettingRecoveryModule(context).init()

    assert not portrait_cache.exists()
    assert not portrait_temp.exists()

    assert calls == [
        "list-completed-forgets",
        "backfill:[]:[('session-1', 'message-1'), ('session-1', 'message-2')]",
        "list-completed-forgets",
        "recover-global-clear",
        "recover-forget-surfaces",
    ]
