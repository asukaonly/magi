"""Public data browsing respects source ownership, privacy and delivery state."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from magi_plugin_sdk.runtime import PluginConnection, SourceChange, SourceChangeBatch

from magi.api.routers import shared_data
from magi.api.routers.sources import sources_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.awareness.source_store import SourceStore
from magi.runtime_trace import RuntimeTraceStore
from magi.runtime_trace.contracts import PluginIngressEventRecord


@pytest.fixture
async def browser(tmp_path, monkeypatch):
    store = SourceStore(tmp_path / 'sources.db')
    trace = RuntimeTraceStore(db_path=str(tmp_path / 'trace.db'))
    await trace.initialize()
    owners = {name: PluginConnection(connection_id=name, plugin_id='health', display_name=name, enabled=True)
              for name in ('phone-a', 'phone-b')}
    visible = set()
    memory = SimpleNamespace(l1=SimpleNamespace(get_user_visible_event=AsyncMock(side_effect=lambda key: {} if key in visible else None)))
    container = SimpleNamespace(source_scheduler_contrib=lambda: SimpleNamespace(source_store=store),
        plugin_manager=lambda: SimpleNamespace(connection_store=SimpleNamespace(get=lambda key: owners[key], ingress_epoch=lambda key: 'epoch')),
        source_registry=lambda: SimpleNamespace(list_contributions=lambda: []),
        unified_memory=lambda: memory, runtime_trace_store=lambda: trace)
    monkeypatch.setattr(shared_data, 'get_container', lambda: container)
    async def accept(owner, oid, version, payload, operation='upsert', outcome='persisted'):
        checkpoint = await store.checkpoint(owners[owner], 'health.records', 'apple_health')
        change = SourceChange(object_id=oid, version=version, payload=payload, operation=operation)
        pending = await store.stage_batch(owners[owner], checkpoint, SourceChangeBatch(changes=[change]))
        if operation == 'upsert':
            await store.record_receipt(pending, change, event_id=owner+oid+version, outcome=outcome)
            visible.add(owner+oid+version)
        await store.accept_batch(owners[owner], pending)
    app = FastAPI()
    app.include_router(_build_public_router(sources_router, _PUBLIC_ROUTE_METHODS['sources']), prefix='/api/sources')
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        yield client, store, trace, accept, visible


@pytest.mark.asyncio
async def test_current_records_filter_page_and_forgetting(browser):
    client, store, _, accept, visible = browser
    await accept('phone-a', 'steps', '1', {'record_type': 'steps', 'start': 100, 'value': 500})
    await accept('phone-a', 'steps', '2', {'record_type': 'steps', 'start': 100, 'value': 900})
    await accept('phone-a', 'sleep', '1', {'record_type': 'sleep', 'start': 200, 'value': 3600})
    await accept('phone-b', 'steps', '1', {'record_type': 'steps', 'start': 100, 'value': 123})
    base='/api/sources/shared/phone-a/health.records/records'
    assert len((await client.get('/api/sources/shared')).json()['items']) == 2
    page=(await client.get(base, params={'limit': 1})).json()
    assert page['items'][0]['object_id'] == 'sleep'
    next_page=(await client.get(base, params={'before': page['next_before']})).json()
    assert [r['payload']['value'] for r in next_page['items']] == [900]
    filtered=(await client.get(base, params={'field':'record_type','value':'steps','date_field':'start','since':50,'until':150})).json()
    assert [r['payload']['value'] for r in filtered['items']] == [900]
    assert (await client.get(base, params={'field':"x') OR 1", 'value':'steps'})).status_code == 422
    assert (await client.get(base, params={'since':100})).status_code == 422
    visible.remove('phone-asteps2')
    assert [r['object_id'] for r in (await client.get(base)).json()['items']] == ['sleep']
    await accept('phone-a', 'sleep', '2', {}, operation='delete')
    assert (await client.get(base)).json()['items'] == []
    assert (await client.get('/api/sources/shared/missing/health.records/records')).status_code == 404
    await store.clear_user_content(connection_id='phone-b')
    assert (await client.get('/api/sources/shared/phone-b/health.records/records')).json()['items'] == []


@pytest.mark.asyncio
async def test_unaccepted_and_governed_revisions_never_exposed(browser):
    client, store, _, accept, _ = browser
    await accept('phone-a', 'private', '1', {'value':42}, outcome='governed_skip')
    assert (await client.get('/api/sources/shared/phone-a/health.records/records')).json()['items'] == []
    assert await store.shared_records(connection_id='phone-a',source_id='health.records',before=None,limit=10) == []


@pytest.mark.asyncio
async def test_history_survives_payload_erasure_and_exact_retry(browser):
    client, _, trace, accept, _ = browser
    await accept('phone-a','steps','1',{'value':42})
    record=PluginIngressEventRecord(event_id=0,source_kind='background_delivery',producer='device',
        connection_id='phone-a',connection_epoch='epoch',plugin_target='health',event_type='source.change.v1',
        occurred_at_ms=1,payload_json='{"private":"hidden"}',source_type='apple_health')
    args=dict(producer_id='device',data_epoch='data',event_id=str(uuid4()),stream='steps',sequence=1,record=record)
    assert await trace.accept_background_event(**args) == 'accepted'
    assert await trace.accept_background_event(**args) == 'accepted'
    item=await trace.claim_next_plugin_ingress_event(consumer_name='test')
    await trace.fail_plugin_ingress_event(item.event_id,error_text='private internal stack')
    base='/api/sources/shared/phone-a/health.records/history'
    body=(await client.get(base)).json()
    assert len(body['items']) == 1 and body['items'][0]['status'] == 'failed'
    assert 'private' not in str(body)
    await trace.retry_source_delivery(connection_id='phone-b',source_type='apple_health',delivery_id=item.event_id)
    assert (await trace.get_plugin_ingress_event(item.event_id)).status == 'failed'
    assert (await client.post(base+f'/{item.event_id}/retry', json={'connection_epoch':'old'})).status_code == 409
    assert (await client.post(base+f'/{item.event_id}/retry', json={'connection_epoch':'epoch'})).status_code == 200
    assert (await trace.get_plugin_ingress_event(item.event_id)).status == 'pending'
    await trace.complete_plugin_ingress_event(item.event_id)
    assert (await trace.get_plugin_ingress_event(item.event_id)).payload_json == '{}'
    reopened=RuntimeTraceStore(db_path=str(trace.db_path))
    assert (await reopened.source_delivery_history(connection_id='phone-a',source_type='apple_health'))[0]['status'] == 'completed'
    await trace.retire_connection_ingress('phone-a')
    assert (await client.get(base)).json()['items'] == []


@pytest.mark.asyncio
async def test_record_cursor_survives_other_connection_clear_and_vacuum(browser):
    client, store, _, accept, _ = browser
    await accept('phone-b', 'first', '1', {'value': 1})
    await accept('phone-a', 'older', '1', {'value': 2})
    await accept('phone-b', 'second', '1', {'value': 3})
    await accept('phone-a', 'newer', '1', {'value': 4})
    base = '/api/sources/shared/phone-a/health.records/records'
    first = (await client.get(base, params={'limit': 1})).json()
    assert first['items'][0]['object_id'] == 'newer'
    await store.clear_user_content(connection_id='phone-b')
    second = (await client.get(base, params={'before': first['next_before']})).json()
    assert [item['object_id'] for item in second['items']] == ['older']
    await store.clear_user_content(connection_id='phone-a')
    await accept('phone-a', 'fresh', '1', {'value': 5})
    assert (await client.get(base)).json()['items'][0]['id'] > first['items'][0]['id']
