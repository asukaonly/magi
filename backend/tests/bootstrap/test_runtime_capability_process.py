"""Exercise the real runtime in an isolated process and data directory."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


_RUNTIME_PROBE = r'''
import os
import sys
os.environ['MAGI_HOME'] = sys.argv[1]
import asyncio
import httpx
from magi.bootstrap.backend import initialize_base_runtime, initialize_agent_runtime, shutdown_agent_runtime
from magi.core.container import get_container, wire_container
from magi.config import get_config, save_config, reload_config
from magi.config.models import LLMProviderSettings, LLMSelectionSettings
from magi.api.services.runtime_status_service import get_runtime_system_status
from magi.transport.http_app import create_transport_app

async def main():
    wire_container()
    config = get_config()
    for layer in (config.agent.memory.l1, config.agent.memory.l2, config.agent.memory.l3, config.agent.memory.l4):
        layer.vectors_enabled = False
    assert save_config({"agent.memory": config.agent.memory.model_dump(mode="json")})
    reload_config()
    await initialize_base_runtime()
    app = create_transport_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated') as client:
        response = await client.get('/api/config/')
        assert response.status_code == 200, response.text[:100]
    try:
        await initialize_agent_runtime()
        context = get_container().runtime_bootstrap_context()
        store, chat, bus = context.memory.unified_memory, context.chat.store, context.message_bus.message_bus
        assert store is not None and not store.l2_pipeline._stats.is_running
        assert (await get_runtime_system_status(app))['storage_ready']
        from magi.memory.event_contracts import MemoryEvent, MemoryDomain, IngestTarget, TomDepth, RetentionClass
        import time
        event = MemoryEvent(
            event_id="isolated-source-event", correlation_id="isolated-source", timestamp=time.time(),
            created_at=time.time(), event_type="SOURCE_EVENT", source="isolated-source", source_item_id="1",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY, ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=False, tom_depth=TomDepth.NONE, retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None, turn_id=None, user_id=None, task_id=None, content="Isolated raw source record",
            author_type="source", content_type="observation", importance_score=0.5, level=20,
        )
        ingested = await store.ingest_event(event)
        assert ingested["l1_written"]
        assert (await store.l1.get_memory_event(event.event_id)).content == event.content
        provider = LLMProviderSettings(provider_type='openai', display_name='Isolated')
        provider.api_key = 'test-only'
        provider.services.chat.api_key = 'test-only'
        provider.base_url = provider.services.chat.base_url = 'http://127.0.0.1:9/v1'
        config.llm.timeout = 1
        config.llm.providers['isolated'] = provider
        config.llm.selections['core'] = LLMSelectionSettings(provider_id='isolated', model='gpt-4o-mini')
        for expected in (True, False, True):
            config.llm.providers['isolated'].enabled = expected
            assert save_config({"llm.providers": {k:v.model_dump(mode="json") for k,v in config.llm.providers.items()}, "llm.selections": {k:v.model_dump(mode="json") for k,v in config.llm.selections.items()}})
            reload_config()
            await asyncio.wait_for(initialize_agent_runtime(), 20)
            status = await get_runtime_system_status(app)
            failed = {k: v for k,v in status['capabilities'].items() if v['state']=='failed'}
            print('ROUNDTRIP', expected, status['runtime_ready'], failed, flush=True)
            assert not failed, failed
            assert status['runtime_ready'] == expected, status
            assert context.memory.unified_memory is store
            assert context.chat.store is chat and context.message_bus.message_bus is bus
            assert store.l2_pipeline._stats.is_running == expected
            assert (await store.l1.get_memory_event(event.event_id)).content == event.content
    finally:
        await shutdown_agent_runtime(strict=True)
asyncio.run(main())
'''


def test_model_configuration_reuses_storage_and_resumes_capabilities(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": str(repo / "backend/src")}
    result = subprocess.run(
        [sys.executable, "-c", _RUNTIME_PROBE, str(tmp_path / "service")],
        env=env, cwd=repo, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-6000:]
    assert result.stdout.count("ROUNDTRIP") == 3
