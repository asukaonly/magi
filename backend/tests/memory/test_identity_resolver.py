from __future__ import annotations


def test_default_identity_resolver_maps_web_runtime_to_self():
    from magi.memory.identity_resolver import IdentityResolver

    resolver = IdentityResolver.in_memory_default()

    result = resolver.resolve_memory_owner_id(runtime_user_id="web_user", source="chat")

    assert result == "user:self"


def test_identity_resolver_allows_multiple_runtime_accounts_for_same_self():
    from magi.memory.identity_resolver import IdentityResolver

    resolver = IdentityResolver.in_memory_default(
        links=[
            ("web", "web_user", "user:self"),
            ("telegram", "asuka_main", "user:self"),
        ]
    )

    assert resolver.resolve_memory_owner_id(runtime_user_id="web_user", source="web") == "user:self"
    assert resolver.resolve_memory_owner_id(runtime_user_id="asuka_main", source="telegram") == "user:self"
