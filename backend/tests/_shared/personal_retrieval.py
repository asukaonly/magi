"""Use the production personal coordinator with isolated local-memory ports."""
from types import SimpleNamespace
from dataclasses import fields
from unittest.mock import AsyncMock
from magi.awareness.retrieval.service import PersonalRetrievalService
from magi.memory.hybrid_retrieval.models import RetrievalPayload
from magi.plugins.sources import SourceRegistry


def personal_port(memory_port):
    async def query(request):
        value = await memory_port.query(request)
        if isinstance(value, RetrievalPayload):
            return value
        values = {field.name: getattr(value, field.name, None) for field in fields(RetrievalPayload)}
        return RetrievalPayload(**{key: value for key, value in values.items() if isinstance(value, (list, dict))})
    service = PersonalRetrievalService(
        memory=SimpleNamespace(query=query), registry=SourceRegistry(), store=None,
        get_connection=lambda _: None,
        governance=SimpleNamespace(capture=AsyncMock(return_value=0), unchanged=AsyncMock(return_value=True)),
        resolve_names=memory_port.get_canonical_names,
    )
    async def retrieve(request, *, source_scope, retrieval_policy, context):
        return await service.retrieve(request, source_scope=source_scope, retrieval_policy=retrieval_policy)
    return SimpleNamespace(retrieve=retrieve)
