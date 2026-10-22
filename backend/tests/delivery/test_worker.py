"""Exercise transport failures through the real durable chat outbox."""
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from magi_plugin_sdk.delivery import DeliveryReceipt

from magi.delivery.worker import DeliveryWorker
from tests.chat.test_outbound_delivery import seed


@pytest.mark.asyncio
@pytest.mark.parametrize("safe", [True, False])
async def test_uncertain_send_retries_only_with_same_provider_key(runtime_paths_with_schema, safe):
    store, _, _ = await seed(runtime_paths_with_schema)
    now = [200]
    calls = []

    async def send(target, content):
        calls.append((target, content.delivery_id))
        if len(calls) == 1:
            raise TimeoutError("Provider outcome unknown")
        return DeliveryReceipt(target.channel_type, "receipt-1", now[0], target.magi_session_id, content.delivery_id)

    sender = SimpleNamespace(supports_idempotent_delivery=safe, deliver=send)
    worker = DeliveryWorker(outbox=store, resolve=lambda _: sender, clock_ms=lambda: now[0])
    assert await worker.run_once()
    now[0] = 2000
    assert await worker.run_once() is safe
    result, = await store.list_outbound_deliveries(message_id="m1")
    if safe:
        assert len(calls) == 2 and calls[0] == calls[1]
        assert result.state == "succeeded"
    else:
        assert len(calls) == 1
        assert result.state == "uncertain"


@pytest.mark.asyncio
async def test_unavailable_channel_does_not_count_as_provider_attempt(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema)
    worker = DeliveryWorker(outbox=store, resolve=lambda _: None, clock_ms=lambda: 200)
    assert await worker.run_once()
    assert not await worker.run_once()
    item, = await store.list_outbound_deliveries(message_id="m1")
    assert item.attempt_count == 0 and item.state == "pending"


@pytest.mark.asyncio
async def test_wrong_receipt_keeps_uncertain_evidence(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema)
    sender = SimpleNamespace(supports_idempotent_delivery=False, deliver=AsyncMock(
        return_value=DeliveryReceipt("account:telegram", "receipt-1", 200, "another-session", "wrong-id"),
    ))
    worker = DeliveryWorker(outbox=store, resolve=lambda _: sender, clock_ms=lambda: 200)
    assert await worker.run_once()
    assert not await worker.run_once()
    item, = await store.list_outbound_deliveries(message_id="m1")
    assert item.state == "uncertain" and item.receipt is None


async def exercise_speech_and_text_delivery(store, *, content, plan, outcome):
    from magi.channels.audio_delivery import AudioDeliveryRouter
    from magi.channels.speech_delivery import SpeechDeliverySender
    from magi_plugin_sdk.audio import AudioPlaybackReceipt, AudioPlaybackState
    from magi.speech.tts.engines import pcm_wav

    async def play(target, clip, request_id):
        if outcome == 'timeout':
            raise TimeoutError('Playback may have started')
        return AudioPlaybackReceipt(target, request_id, 'playback-1', AudioPlaybackState.ACCEPTED)
    audio_channel = SimpleNamespace(play_audio=AsyncMock(side_effect=play))
    synthesize = AsyncMock(return_value=pcm_wav(b'\0\0' * 800, 8000))
    if outcome == 'synthesis_failure':
        synthesize.side_effect = ValueError('model_missing')
    speaker = SpeechDeliverySender(AudioDeliveryRouter(SimpleNamespace(get_audio=lambda _: audio_channel)), synthesize)
    async def text(target, request):
        return DeliveryReceipt(target.channel_type, 'text-1', 202, target.magi_session_id, request.delivery_id)
    phone = SimpleNamespace(supports_idempotent_delivery=False, deliver=AsyncMock(side_effect=text))
    resolve = lambda key: speaker if key == 'home:speaker' else phone
    worker = DeliveryWorker(outbox=store, resolve=resolve, clock_ms=lambda: 202)
    assert await worker.run_once()
    assert await worker.run_once()
    restarted = DeliveryWorker(outbox=store, resolve=resolve, clock_ms=lambda: 70000)
    assert not await restarted.run_once()
    records = {item.endpoint.registry_key: item for item in await store.list_outbound_deliveries(message_id=content.message_id)}
    assert records['phone:message'].state == 'succeeded'
    assert records['home:speaker'].state == {'accepted': 'succeeded', 'timeout': 'uncertain', 'synthesis_failure': 'failed'}[outcome]
    phone.deliver.assert_awaited_once()
    assert audio_channel.play_audio.await_count == (0 if outcome == 'synthesis_failure' else 1)
    if outcome == 'accepted':
        persisted = records['home:speaker'].receipt
        assert persisted.playback.state is AudioPlaybackState.ACCEPTED
        assert persisted.playback.target.target_id == 'kitchen'
        status = next(item for item in await store.list_recent_outbound_status() if item.endpoint.registry_key == 'home:speaker')
        assert status.playback_state is AudioPlaybackState.ACCEPTED


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['accepted', 'timeout', 'synthesis_failure'])
async def test_audio_and_phone_delivery_remain_independent_after_restart(runtime_paths_with_schema, outcome):
    from magi.chat.storage.outbound_delivery import insert_outbound_deliveries
    from magi.delivery.routing import DeliveryPlan
    from magi_plugin_sdk.endpoints import EndpointRef
    store, _, content = await seed(runtime_paths_with_schema)
    plan = DeliveryPlan('s1', 'u1', (EndpointRef('phone', 'message', 'owner'), EndpointRef('home', 'speaker', 'kitchen')))
    async with store.database.session() as db:
        await db.execute('DELETE FROM chat_outbound_deliveries')
        await insert_outbound_deliveries(db, content=content, plan=plan, now_ms=200)
        await db.commit()
    await exercise_speech_and_text_delivery(store, content=content, plan=plan, outcome=outcome)
