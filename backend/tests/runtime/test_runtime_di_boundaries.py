"""Runtime ownership contracts; dependency direction is enforced by .importlinter."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dependency_injector import providers

from magi.core.container import Container


@pytest.fixture
def runtime_containers():
    owners = [Container(), Container()]
    try:
        yield owners
    finally:
        for owner in owners:
            owner.unwire()


def test_bootstrap_owners_remain_bound_to_the_selected_container(monkeypatch, runtime_containers):
    from magi.bootstrap import backend

    current = [runtime_containers[0]]
    built = []

    def modules(context):
        built.append(context)
        return []

    monkeypatch.setattr(backend, "get_container", lambda: current[0])
    monkeypatch.setattr(backend, "build_runtime_modules", modules)
    first = backend._runtime_owner()
    current[0] = runtime_containers[1]
    second = backend._runtime_owner()
    assert first[0] is not second[0]
    assert first[1] is not second[1]
    for index, expected in [(0, first), (1, second), (0, first)]:
        current[0] = runtime_containers[index]
        actual = backend._runtime_owner()
        assert actual[0] is expected[0]
        assert actual[1] is expected[1]
        assert current[0].runtime_orchestrator() is expected[0]
        assert current[0].runtime_bootstrap_context() is expected[1]
    assert built == [first[1], second[1]]


@pytest.mark.parametrize(
    "module_name,binding,resolver_name",
    [
        ("magi.plugins.provider", "plugin_manager", "resolve_plugin_manager"),
        ("magi.plugins.provider", "plugin_projection_service", "resolve_plugin_projection_service"),
        ("magi.plugins.provider", "source_registry", "resolve_source_registry"),
        ("magi.memory.provider", "unified_memory", "get_unified_memory"),
        ("magi.memory.provider", "hybrid_retrieval_service", "get_hybrid_retrieval_service"),
        ("magi.skills.provider", "skill_indexer", "resolve_skill_indexer"),
        ("magi.core.runtime_bindings", "agent_runtime", "require_agent_runtime"),
        ("magi.scheduler.provider", "scheduler_service", "require_scheduler_service"),
    ],
)
def test_runtime_services_follow_container_switches_and_do_not_reuse_unbound_instances(
    monkeypatch, runtime_containers, module_name, binding, resolver_name
):
    module = import_module(module_name)
    resolve = getattr(module, resolver_name)
    current = [runtime_containers[0]]
    monkeypatch.setattr("magi.core.container.get_container", lambda: current[0])
    with pytest.raises(RuntimeError, match=binding):
        resolve()
    instances = [object(), object()]
    for owner, instance in zip(runtime_containers, instances):
        getattr(owner, binding).override(providers.Object(instance))
    for index in [0, 1, 0, 1]:
        current[0] = runtime_containers[index]
        assert resolve() is instances[index]
    getattr(runtime_containers[1], binding).reset_override()
    with pytest.raises(RuntimeError, match=binding):
        resolve()
    current[0] = runtime_containers[0]
    assert resolve() is instances[0]


@pytest.mark.asyncio
async def test_independently_built_skill_runtimes_execute_their_own_loaded_content(monkeypatch):
    from magi.skills import service_access
    from magi.skills.schema import SkillContent, SkillFrontmatter

    monkeypatch.setattr(service_access, "_get_enabled_skill_names", lambda: {"shared"})
    runtimes = []
    registries = []
    loaders = []
    for label in ["first", "second"]:
        metadata = object()
        indexer = SimpleNamespace(
            scan_all=Mock(return_value={"shared": metadata, "disabled": object()})
        )
        skill = SkillContent(
            name="shared",
            frontmatter=SkillFrontmatter(name="shared", description=label),
            prompt_template=f"{label} content",
        )
        loader = SimpleNamespace(indexer=indexer, load_skill=Mock(return_value=skill))
        registry = SimpleNamespace(bind_skill_indexer=Mock(), register_skill_index=Mock())
        runtime = service_access.build_skills_runtime(
            tool_registry=registry, skill_indexer=indexer, skill_loader=loader
        )
        registry.bind_skill_indexer.assert_called_once_with(indexer)
        registry.register_skill_index.assert_called_once_with({"shared": metadata})
        assert runtime.skill_indexer is indexer
        assert runtime.skill_loader is loader
        runtimes.append(runtime)
        registries.append(registry)
        loaders.append(loader)
    for index, expected in [(0, "first content"), (1, "second content"), (0, "first content")]:
        result = await runtimes[index].skill_runner.execute("shared")
        assert result.success is True
        assert result.content == expected
    assert [loader.load_skill.call_count for loader in loaders] == [2, 1]
    for registry in registries:
        assert registry.register_skill_index.call_count == 1


@pytest.mark.asyncio
async def test_timeline_handlers_consult_their_own_injected_source_and_package(monkeypatch):
    from magi.config import AppConfig
    from magi.timeline.handler import build_timeline_handler

    handlers = []
    registries = []
    managers = []
    for label, package in [("first", None), ("second", object())]:
        source = SimpleNamespace(connection=SimpleNamespace(enabled=True))
        spec = SimpleNamespace(domain="other")
        registry = SimpleNamespace(
            resolve_source=Mock(return_value=(label, "source", source, spec))
        )
        manager = SimpleNamespace(get_package=Mock(return_value=package))
        handlers.append(
            build_timeline_handler(
                AppConfig(), object(), source_registry=registry, plugin_manager=manager
            )
        )
        registries.append(registry)
        managers.append(manager)
    payload = {
        "connection_id": "connection",
        "source_type": "sample",
        "source_change": {
            "object_id": "item",
            "version": "v1",
            "occurred_at": 100.0,
            "payload": {},
        },
    }
    for index, reason in [
        (0, "source_disabled"),
        (1, "unsupported_source"),
        (0, "source_disabled"),
    ]:
        assert await handlers[index](payload) == {
            "handled": False,
            "reason": reason,
            "source_type": "sample",
        }
    assert [registry.resolve_source.call_count for registry in registries] == [2, 1]
    assert [manager.get_package.call_count for manager in managers] == [2, 1]
    for label, registry, manager in zip(["first", "second"], registries, managers):
        registry.resolve_source.assert_called_with("sample", connection_id="connection")
        manager.get_package.assert_called_with(label)
