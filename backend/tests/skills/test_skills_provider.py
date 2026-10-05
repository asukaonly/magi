from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.skills.provider import resolve_skill_indexer


def test_skill_indexer_binding_lifecycle():
    container = get_container()
    with pytest.raises(RuntimeError, match="skill_indexer"):
        resolve_skill_indexer()
    indexer = object()
    with container.skill_indexer.override(providers.Object(indexer)):
        assert resolve_skill_indexer() is indexer
    with pytest.raises(RuntimeError, match="skill_indexer"):
        resolve_skill_indexer()
