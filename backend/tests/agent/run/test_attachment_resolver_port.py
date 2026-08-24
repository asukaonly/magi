from __future__ import annotations

from magi.agent.execution.attachment_resolver import (
    AttachmentResolverPort,
    LazyAttachmentResolver,
    NullAttachmentResolver,
)


def test_null_attachment_resolver_returns_none_payload() -> None:
    resolver = NullAttachmentResolver()
    assert resolver.get_attachment_payload("user-1", "session-1", "att-1") is None


def test_null_attachment_resolver_satisfies_port_protocol() -> None:
    resolver: AttachmentResolverPort = NullAttachmentResolver()
    # A null resolver must be usable anywhere a resolver port is expected
    # without touching chat / a read service.
    assert resolver.get_attachment_payload("u", "s", "a") is None


def test_lazy_attachment_resolver_delegates_to_factory_lazily() -> None:
    calls: list[tuple[str, str, str]] = []
    constructed: list[int] = []

    class _FakeReadService:
        def get_attachment_payload(
            self, user_id: str, session_id: str, attachment_id: str
        ) -> dict[str, object] | None:
            calls.append((user_id, session_id, attachment_id))
            return {"storage_path": "/runtime/chat/x.png"}

    def _factory() -> _FakeReadService:
        constructed.append(1)
        return _FakeReadService()

    resolver = LazyAttachmentResolver(_factory)
    # Constructing the resolver must NOT call the factory (lazy singleton
    # semantics: the read service is only fetched at resolve time).
    assert constructed == []

    payload = resolver.get_attachment_payload("user-1", "session-1", "att-1")

    assert constructed == [1]
    assert calls == [("user-1", "session-1", "att-1")]
    assert payload == {"storage_path": "/runtime/chat/x.png"}
