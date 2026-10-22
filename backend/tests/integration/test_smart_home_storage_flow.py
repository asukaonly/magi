"""Real MySQL/Chroma integration with controlled device and speech adapters.

No LLM or physical home platform is exercised: this verifies host ownership,
transactional output, restart safety and clear fencing across production services.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

import pytest
from magi_plugin_sdk.audio import AudioOutputTarget, AudioPlaybackReceipt, AudioPlaybackState
from magi_plugin_sdk.delivery import DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef, IngressContext
from magi_plugin_sdk.runtime import OperationResult, OperationSpec, PluginConnection

from magi.agent.background import BackgroundTaskStore
from magi.agent.execution.plugin_operation_invoker import build_plugin_operation_invoker
from magi.agent.run_triggers import build_user_message_trigger
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.structured_storage import StructuredStorageModule
from magi.channels.audio_delivery import AudioDeliveryRouter
from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi.channels.speech_delivery import SpeechDeliverySender
from magi.chat.contracts import ChatMessageRecord
from magi.delivery.worker import DeliveryWorker
from magi.memory.l1.event_store import L1EventStore
from magi.plugins.operation_authorization import build_host_invocation
from magi.plugins.operations import PluginOperationRegistry
from magi.speech.tts.engines import pcm_wav
from magi.tools.registry import ToolRegistry
from channels.test_storage_transfer import environment as environment
from memory.test_vector_factory import _chroma_factory
from memory.test_clear_embedding_barrier import _DeterministicEmbeddingService, _user_message


def operation_runtime(paths, effect):
    connection = PluginConnection(connection_id='house', plugin_id='home', display_name='Home', enabled=True)
    tools = ToolRegistry()
    tools.bind_tool_effect_ledger(BackgroundTaskStore(db_path=str(paths.background_tasks_db_path)))
    operations = PluginOperationRegistry(tools, invoke_tool=build_plugin_operation_invoker(tools),
        get_connection=lambda identifier: connection if identifier == 'house' else None,
        authorize=lambda *_: True, publish_progress=AsyncMock(), validate_resource=lambda *_: True)
    operations.register(plugin_id='home', connection_id='house', handler=effect, spec=OperationSpec(
        operation_id='set_light', description='Set the selected light',
        input_schema={'type': 'object', 'properties': {'on': {'type': 'boolean'}}, 'required': ['on'], 'additionalProperties': False},
        output_schema={'type': 'object', 'properties': {'on': {'type': 'boolean'}}, 'required': ['on'], 'additionalProperties': False},
        triggers=['user'], effect='external_write', replay='non_idempotent',
    ))
    return operations, connection


@pytest.mark.parametrize('audio_uncertain', [False, True])
async def test_phone_operation_text_speech_restart_and_clear(environment, ensure_db_schema, audio_uncertain):
    paths, settings = environment
    for chain, path in [('background_tasks', paths.background_tasks_db_path), ('runtime_trace', paths.runtime_trace_db_path)]:
        ensure_db_schema(chain, path)
    settings = settings.model_copy(update={'chat': 'mysql', 'memory_events': 'mysql'})
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.config = SimpleNamespace(structured_storage=settings)
    module = StructuredStorageModule(context)
    factory = _chroma_factory(paths.memory_dir, ensure_db_schema)
    memory = None
    now = int(time.time() * 1000)
    clock = [now + 10]
    phone = EndpointRef('mobile', 'message', 'owner', 'home')
    speaker = EndpointRef('house', 'speaker', 'living-room')
    ingress = IngressContext(kind='message', origin=phone, reply_to=phone, event_id='phone-request', channel_clear_generation=0)
    trigger = build_user_message_trigger(source=phone.registry_key, requester='u1', content='Switch off the light',
        turn_id='turn-1', ingress=ingress, delivery_targets=(speaker,))
    dispatcher = ChatDeliveryDispatcher.from_registry(channel_registry=SimpleNamespace(get=lambda _: None))
    plan = await dispatcher.resolve_delivery_plan(SimpleNamespace(
        session_id='session-1', user_id='u1', active_run=SimpleNamespace(trigger=trigger)))
    assert phone in plan.targets and speaker in plan.targets
    effect = AsyncMock(return_value=OperationResult(status='succeeded', value={'on': False}))
    operations, connection = operation_runtime(paths, effect)
    identity = build_host_invocation(connection, trigger='user', task_id='turn-1', session_id='session-1')
    phone_online = [False]
    async def send_text(target, content):
        return DeliveryReceipt(target.channel_type, 'phone-receipt', clock[0], target.magi_session_id, content.delivery_id)
    text_sender = SimpleNamespace(supports_idempotent_delivery=False, deliver=AsyncMock(side_effect=send_text))
    async def play(target, clip, request_id):
        assert target == AudioOutputTarget('house:speaker', 'living-room')
        if audio_uncertain:
            raise TimeoutError('Device playback outcome is unknown')
        return AudioPlaybackReceipt(target, request_id, 'speaker-receipt', AudioPlaybackState.ACCEPTED)
    device = SimpleNamespace(play_audio=AsyncMock(side_effect=play))
    speech = SpeechDeliverySender(AudioDeliveryRouter(SimpleNamespace(get_audio=lambda _: device)),
        AsyncMock(return_value=pcm_wav(b'\0\0' * 800, 8000)))
    def resolve(key):
        return speech if key == speaker.registry_key else text_sender if phone_online[0] else None
    try:
        await module.init()
        memory = L1EventStore(event_repository=context.memory.event_repository, vector_index_factory=factory,
            embedding_service=_DeterministicEmbeddingService(), async_embeddings=False)
        await memory.initialize()
        store = context.chat.store
        await store.create_user_turn_once(session_id='session-1', user_id='u1', turn_id='turn-1',
            message_text='Switch off the light', created_at_ms=now,
            runtime_envelope={'ingress': ingress.to_dict(), 'delivery_targets': [speaker.to_dict()]},
            request_fingerprint='phone-request-fingerprint')
        assert (await operations.invoke('house', 'set_light', {'on': False}, identity=identity)).status == 'succeeded'
        response = ChatMessageRecord('result-1', 'session-1', 'turn-1', 'u1', 'assistant', 'assistant_final',
            'The light is off.', '{}', True, True, now + 1, 2, None, None)
        assert await store.commit_unmanaged_assistant_outcome(post_turn_source='conversation', turn_id='turn-1', messages=[response],
            attachment_payloads_by_message_id={}, trace_id=None, execution_mode='direct_llm', ux_plan={},
            response_mode='final_only', started_at_ms=now, completed_at_ms=now + 1, delivery_plan=plan)
        await memory.store(_user_message(event_id='light-result', content=response.content_text))
        hits = await memory.vector_search(query='light')
        assert hits and await memory.search_events(query='light')
        worker = DeliveryWorker(outbox=store, resolve=resolve, clock_ms=lambda: clock[0])
        assert await worker.run_once()
        assert await worker.run_once()
        assert not await worker.run_once()
        states = {item.endpoint: item.state for item in await store.list_outbound_deliveries(message_id='result-1')}
        assert states == {phone: 'pending', speaker: 'uncertain' if audio_uncertain else 'succeeded'}
        await memory.shutdown()
        await factory.close()
        await module.shutdown()
        # New driver pools, service objects and effect ledger simulate a worker restart.
        await module.init()
        store = context.chat.store
        factory = _chroma_factory(paths.memory_dir, ensure_db_schema)
        memory = L1EventStore(event_repository=context.memory.event_repository, vector_index_factory=factory,
            embedding_service=_DeterministicEmbeddingService(), async_embeddings=False)
        await memory.initialize()
        operations, _ = operation_runtime(paths, effect)
        replay = await operations.invoke('house', 'set_light', {'on': False}, identity=identity)
        assert replay.error_code == 'TOOL_EFFECT_ALREADY_COMPLETED'
        phone_online[0] = True
        clock[0] += 70000
        worker = DeliveryWorker(outbox=store, resolve=resolve, clock_ms=lambda: clock[0])
        assert await worker.run_once()
        assert not await worker.run_once()
        effect.assert_awaited_once()
        text_sender.deliver.assert_awaited_once()
        device.play_audio.assert_awaited_once()
        assert (await context.chat.reader.aget_display_message('u1', 'session-1', 'result-1')).content == response.content_text
        assert await memory.search_events(query='light')
        await context.chat.reader.aclear_conversation_history('u1', 'session-1')
        await memory.clear(restart_workers=False)
        # A stale external vector is only a candidate; authoritative records reject it.
        await factory.create('l1').upsert(entity_id=hits[0].entity_id,
            embedding=_DeterministicEmbeddingService._result('light'))
        assert await memory.search_events(query='light') == []
        assert not await worker.run_once()
        assert await store.list_recent_outbound_status() == []
        assert await memory.rebuild_embeddings(batch_size=1) == 0
        assert await memory.vector_search(query='light') == []
    finally:
        if memory is not None:
            await memory.shutdown()
        await factory.clear_all()
        await factory.close()
        await module.shutdown()
