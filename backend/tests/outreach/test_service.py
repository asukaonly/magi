import pytest
import asyncio
from magi.delivery.contracts import DeliveryFailure, DeliveryFanoutResult
from magi.outreach.contracts import (
    GovernorVerdict,
    OutreachIntent,
    OutreachKind,
    ResolvedTargets,
    Urgency,
)
from magi.outreach.executor import ExternalChannelDeliveryError
from magi.outreach.identity import (
    canonical_intent_json,
    intent_fingerprint,
)
from magi.outreach.service import OutreachService
from magi.outreach.stores import OutboxEnqueueResult
from magi_plugin_sdk.channels import ChannelTarget


def _intent(urgency=Urgency.NORMAL, correlation_id="c1"):
    return OutreachIntent(kind=OutreachKind.TASK_COMPLETED, user_id="u1",
                          origin_session_id="s1", title="t", facts="f",
                          correlation_id=correlation_id, completed_at_ms=1,
                          urgency=urgency)


def _ext_target():
    return ChannelTarget(channel_type="telegram", external_chat_id="X1",
                         magi_session_id="s1", magi_user_id="u1")


def _outbox_row(intent, *, row_id=7, channel_scope="telegram", release_at_ms=1):
    return {
        "id": row_id,
        "correlation_id": intent.correlation_id,
        "channel_scope": channel_scope,
        "intent_fingerprint": intent_fingerprint(intent),
        "intent_json": canonical_intent_json(intent),
        "release_at_ms": release_at_ms,
    }


class _Resolver:
    def __init__(self, targets): self._t = targets
    async def resolve(self, intent): return self._t


class _Governor:
    def __init__(self, verdict, release=None): self._v, self._r = verdict, release
    async def evaluate(self, intent, *, external_target): return self._v, self._r


class _Desktop:
    def __init__(self): self.writes = []
    async def write(self, intent, body): self.writes.append((intent, body))


class _External:
    def __init__(self): self.pushes = []
    async def push(self, intent, body, *, target):
        self.pushes.append((intent, body, target))
        return ["r"]


class _Outbox:
    def __init__(self):
        self.enqueued = []
        self.statuses = []
        self.rescheduled = []
    async def enqueue(self, **values):
        self.enqueued.append(values)
        return OutboxEnqueueResult(row_id=1, status="pending", created=True)
    async def begin_delivery_attempt(self, row_id):
        self.statuses.append((row_id, "attempting"))
        return True
    async def mark_status(self, row_id, status):
        self.statuses.append((row_id, status))
    async def reschedule(self, row_id, *, release_at_ms):
        self.rescheduled.append((row_id, release_at_ms))


class _Log:
    def __init__(self): self.records = []
    async def record(self, **kw): self.records.append(kw)
    async def was_delivered(self, correlation_id, channel_type):
        return any(
            record["correlation_id"] == correlation_id
            and record["channel_type"] == channel_type
            for record in self.records
        )


async def _compose(intent): return "magi-voiced body"


def _service(targets, verdict, release=None, desktop=None, external=None, outbox=None, log=None):
    return OutreachService(
        compose=_compose, target_resolver=_Resolver(targets),
        governor=_Governor(verdict, release),
        desktop_executor=desktop or _Desktop(),
        external_executor=external or _External(),
        outbox=outbox or _Outbox(), delivery_log=log or _Log(),
    )


@pytest.mark.asyncio
async def test_submit_external_origin_writes_desktop_and_pushes():
    desktop, external, log, outbox = _Desktop(), _External(), _Log(), _Outbox()
    svc = _service(ResolvedTargets("s1", _ext_target()), GovernorVerdict.PUSH_NOW,
                   desktop=desktop, external=external, outbox=outbox, log=log)
    await svc.submit(_intent())
    assert desktop.writes and desktop.writes[0][1] == "magi-voiced body"
    assert external.pushes and external.pushes[0][1] == "magi-voiced body"
    assert log.records and log.records[0]["correlation_id"] == "c1"
    assert len(outbox.enqueued) == 1
    assert outbox.statuses == [(1, "attempting"), (1, "delivered")]


@pytest.mark.asyncio
async def test_submit_desktop_origin_only():
    desktop, external = _Desktop(), _External()
    svc = _service(ResolvedTargets("s1", None), GovernorVerdict.PUSH_NOW,
                   desktop=desktop, external=external)
    await svc.submit(_intent())
    assert desktop.writes and not external.pushes


@pytest.mark.asyncio
async def test_submit_persists_new_composition_before_delivery_side_effect():
    events = []

    async def compose(intent):
        events.append(("compose", intent.correlation_id))
        return "prepared once"

    class _OrderedDesktop:
        async def write(self, intent, body):
            events.append(("desktop", intent.correlation_id, body))

    async def persist_body(body):
        events.append(("persist", body))

    service = OutreachService(
        compose=compose,
        target_resolver=_Resolver(ResolvedTargets("s1", None)),
        governor=_Governor(GovernorVerdict.PUSH_NOW),
        desktop_executor=_OrderedDesktop(),
        external_executor=_External(),
        outbox=_Outbox(),
        delivery_log=_Log(),
    )

    await service.submit(
        _intent(),
        persist_composed_body=persist_body,
    )

    assert events == [
        ("compose", "c1"),
        ("persist", "prepared once"),
        ("desktop", "c1", "prepared once"),
    ]


@pytest.mark.asyncio
async def test_submit_reuses_prepared_body_without_recomposing():
    async def compose(_intent):
        raise AssertionError("prepared completion must not be recomposed")

    desktop = _Desktop()
    service = OutreachService(
        compose=compose,
        target_resolver=_Resolver(ResolvedTargets("s1", None)),
        governor=_Governor(GovernorVerdict.PUSH_NOW),
        desktop_executor=desktop,
        external_executor=_External(),
        outbox=_Outbox(),
        delivery_log=_Log(),
    )

    await service.submit(_intent(), prepared_body="already prepared")

    assert desktop.writes[0][1] == "already prepared"


@pytest.mark.asyncio
async def test_conversation_clear_boundary_blocks_new_outreach():
    desktop, external = _Desktop(), _External()
    service = _service(
        ResolvedTargets("s1", _ext_target()),
        GovernorVerdict.PUSH_NOW,
        desktop=desktop,
        external=external,
    )

    async with service.conversation_clear_boundary():
        pending_submit = asyncio.create_task(service.submit(_intent()))
        await asyncio.sleep(0)
        assert desktop.writes == []
        assert external.pushes == []

    await pending_submit
    assert len(desktop.writes) == 1
    assert len(external.pushes) == 1


@pytest.mark.asyncio
async def test_submit_defer_enqueues_outbox_not_push():
    external, outbox = _External(), _Outbox()
    svc = _service(ResolvedTargets("s1", _ext_target()), GovernorVerdict.DEFER, release=999,
                   external=external, outbox=outbox)
    await svc.submit(_intent())
    assert not external.pushes
    assert len(outbox.enqueued) == 1
    assert outbox.rescheduled == [(1, 999)]


@pytest.mark.asyncio
async def test_submit_push_now_does_not_call_channel_when_claim_write_fails():
    class _FailingClaimOutbox(_Outbox):
        async def begin_delivery_attempt(self, row_id):
            _ = row_id
            raise RuntimeError("outbox claim unavailable")

    external = _External()
    outbox = _FailingClaimOutbox()
    service = _service(
        ResolvedTargets("s1", _ext_target()),
        GovernorVerdict.PUSH_NOW,
        external=external,
        outbox=outbox,
    )

    with pytest.raises(RuntimeError, match="outbox claim unavailable"):
        await service.submit(_intent())

    assert len(outbox.enqueued) == 1
    assert external.pushes == []


@pytest.mark.asyncio
async def test_drain_due_pushes_and_marks_delivered():
    external, log = _External(), _Log()

    class _DrainOutbox:
        def __init__(self): self.marked = []
        async def list_due(self, *, now_ms):
            return [_outbox_row(_intent())]
        async def begin_delivery_attempt(self, row_id):
            self.marked.append((row_id, "attempting"))
            return True
        async def mark_status(self, row_id, status): self.marked.append((row_id, status))

    outbox = _DrainOutbox()
    svc = _service(ResolvedTargets(None, _ext_target()), GovernorVerdict.PUSH_NOW,
                   external=external, outbox=outbox, log=log)
    await svc.drain_due(now_ms=1000)
    assert external.pushes and outbox.marked == [
        (7, "attempting"),
        (7, "delivered"),
    ]


@pytest.mark.asyncio
async def test_drain_due_reschedules_deferred_row_without_recomposing_each_cycle():
    class _DrainOutbox:
        def __init__(self):
            self.rescheduled = []

        async def list_due(self, *, now_ms):
            if self.rescheduled and self.rescheduled[-1][1] > now_ms:
                return []
            return [_outbox_row(_intent())]

        async def reschedule(self, row_id, *, release_at_ms):
            self.rescheduled.append((row_id, release_at_ms))

    compose_calls = []

    async def _counting_compose(intent):
        compose_calls.append(intent.correlation_id)
        return "body"

    outbox = _DrainOutbox()
    service = OutreachService(
        compose=_counting_compose,
        target_resolver=_Resolver(ResolvedTargets(None, _ext_target())),
        governor=_Governor(GovernorVerdict.DEFER, 10_000),
        desktop_executor=_Desktop(),
        external_executor=_External(),
        outbox=outbox,
        delivery_log=_Log(),
    )

    await service.drain_due(now_ms=1_000)
    await service.drain_due(now_ms=2_000)

    assert outbox.rescheduled == [(7, 10_000)]
    assert compose_calls == []


@pytest.mark.asyncio
async def test_drain_due_stops_retry_after_uncertain_delivery_and_continues():
    class _PartiallyFailingExternal:
        def __init__(self):
            self.pushes = []

        async def push(self, intent, body, *, target):
            self.pushes.append(intent.correlation_id)
            if intent.correlation_id == "failed":
                raise RuntimeError("channel unavailable")
            return ["receipt"]

    class _DrainOutbox:
        def __init__(self):
            self.marked = []

        async def list_due(self, *, now_ms):
            failed = _intent(correlation_id="failed")
            delivered = _intent(correlation_id="delivered")
            return [
                _outbox_row(failed, row_id=7),
                _outbox_row(delivered, row_id=8),
            ]

        async def begin_delivery_attempt(self, row_id):
            self.marked.append((row_id, "attempting"))
            return True

        async def mark_status(self, row_id, status):
            self.marked.append((row_id, status))

    external = _PartiallyFailingExternal()
    outbox = _DrainOutbox()
    log = _Log()
    svc = _service(
        ResolvedTargets(None, _ext_target()),
        GovernorVerdict.PUSH_NOW,
        external=external,
        outbox=outbox,
        log=log,
    )

    await svc.drain_due(now_ms=1000)

    assert external.pushes == ["failed", "delivered"]
    assert outbox.marked == [
        (7, "attempting"),
        (7, "uncertain"),
        (8, "attempting"),
        (8, "delivered"),
    ]
    assert [record["correlation_id"] for record in log.records] == ["delivered"]


@pytest.mark.asyncio
async def test_drain_due_keeps_confirmed_pre_delivery_failure_pending():
    class _LookupFailingExternal:
        async def push(self, intent, body, *, target):
            _ = body
            if intent.correlation_id == "lookup-failed":
                raise ExternalChannelDeliveryError(
                    target=target,
                    result=DeliveryFanoutResult(
                        failures=(
                            DeliveryFailure(
                                target=target,
                                error=LookupError("channel not registered"),
                                delivery_attempted=False,
                            ),
                        )
                    ),
                )
            return ["receipt"]

    class _DrainOutbox:
        def __init__(self):
            self.marked = []

        async def list_due(self, *, now_ms):
            _ = now_ms
            return [
                _outbox_row(_intent(correlation_id="lookup-failed"), row_id=7),
                _outbox_row(_intent(correlation_id="delivered"), row_id=8),
            ]

        async def begin_delivery_attempt(self, row_id):
            self.marked.append((row_id, "attempting"))
            return True

        async def restore_pending_after_unattempted_delivery(
            self,
            row_id,
            *,
            intent_json,
        ):
            assert intent_json
            self.marked.append((row_id, "pending"))
            return True

        async def mark_status(self, row_id, status):
            self.marked.append((row_id, status))

    outbox = _DrainOutbox()
    log = _Log()
    service = _service(
        ResolvedTargets(None, _ext_target()),
        GovernorVerdict.PUSH_NOW,
        external=_LookupFailingExternal(),
        outbox=outbox,
        log=log,
    )

    await service.drain_due(now_ms=1000)

    assert outbox.marked == [
        (7, "attempting"),
        (7, "pending"),
        (8, "attempting"),
        (8, "delivered"),
    ]
    assert [record["correlation_id"] for record in log.records] == ["delivered"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["resolver", "compose", "governor"])
async def test_drain_due_isolates_pre_delivery_stage_failures(failure_stage):
    failed = _intent(correlation_id="failed")
    delivered = _intent(correlation_id="delivered")

    class _StageResolver:
        async def resolve(self, intent):
            if (
                failure_stage == "resolver"
                and intent.correlation_id == "failed"
            ):
                raise RuntimeError("resolver unavailable")
            return ResolvedTargets(None, _ext_target())

    async def _stage_compose(intent):
        if (
            failure_stage == "compose"
            and intent.correlation_id == "failed"
        ):
            raise RuntimeError("compose unavailable")
        return f"body:{intent.correlation_id}"

    class _StageGovernor:
        async def evaluate(self, intent, *, external_target):
            _ = external_target
            if (
                failure_stage == "governor"
                and intent.correlation_id == "failed"
            ):
                raise RuntimeError("governor unavailable")
            return GovernorVerdict.PUSH_NOW, None

    class _DrainOutbox:
        def __init__(self):
            self.marked = []

        async def list_due(self, *, now_ms):
            _ = now_ms
            return [
                _outbox_row(failed, row_id=7),
                _outbox_row(delivered, row_id=8),
            ]

        async def begin_delivery_attempt(self, row_id):
            self.marked.append((row_id, "attempting"))
            return True

        async def mark_status(self, row_id, status):
            self.marked.append((row_id, status))

    external = _External()
    outbox = _DrainOutbox()
    service = OutreachService(
        compose=_stage_compose,
        target_resolver=_StageResolver(),
        governor=_StageGovernor(),
        desktop_executor=_Desktop(),
        external_executor=external,
        outbox=outbox,
        delivery_log=_Log(),
    )

    await service.drain_due(now_ms=1000)

    assert [
        intent.correlation_id for intent, _body, _target in external.pushes
    ] == ["delivered"]
    assert outbox.marked == [(8, "attempting"), (8, "delivered")]


@pytest.mark.asyncio
async def test_confirmed_delivery_survives_log_failure_without_retry():
    class _FailingLog(_Log):
        async def record(self, **kw):
            _ = kw
            raise RuntimeError("delivery log unavailable")

    class _DrainOutbox:
        def __init__(self):
            self.status = "pending"

        async def list_due(self, *, now_ms):
            _ = now_ms
            if self.status != "pending":
                return []
            return [_outbox_row(_intent())]

        async def begin_delivery_attempt(self, row_id):
            assert row_id == 7
            if self.status != "pending":
                return False
            self.status = "attempting"
            return True

        async def mark_status(self, row_id, status):
            assert row_id == 7
            self.status = status

    external = _External()
    outbox = _DrainOutbox()
    service = _service(
        ResolvedTargets(None, _ext_target()),
        GovernorVerdict.PUSH_NOW,
        external=external,
        outbox=outbox,
        log=_FailingLog(),
    )

    await service.drain_due(now_ms=1000)
    await service.drain_due(now_ms=1000)

    assert len(external.pushes) == 1
    assert outbox.status == "delivered"


@pytest.mark.asyncio
async def test_attempt_claim_prevents_resend_when_log_and_status_writes_fail():
    class _FailingLog(_Log):
        async def record(self, **kw):
            _ = kw
            raise RuntimeError("delivery log unavailable")

    class _FlakyStatusOutbox:
        def __init__(self):
            self.status = "pending"
            self.mark_attempts = 0

        async def list_due(self, *, now_ms):
            _ = now_ms
            if self.status != "pending":
                return []
            return [_outbox_row(_intent())]

        async def begin_delivery_attempt(self, row_id):
            assert row_id == 7
            if self.status != "pending":
                return False
            self.status = "attempting"
            return True

        async def mark_status(self, row_id, status):
            assert row_id == 7
            self.mark_attempts += 1
            raise RuntimeError("outbox status unavailable")

    external = _External()
    outbox = _FlakyStatusOutbox()
    service = _service(
        ResolvedTargets(None, _ext_target()),
        GovernorVerdict.PUSH_NOW,
        external=external,
        outbox=outbox,
        log=_FailingLog(),
    )

    await service.drain_due(now_ms=1000)
    await service.drain_due(now_ms=1000)

    assert len(external.pushes) == 1
    assert outbox.status == "attempting"
    assert outbox.mark_attempts == 1


@pytest.mark.asyncio
async def test_delivery_attempt_is_not_invoked_when_claim_write_fails():
    class _FailingClaimOutbox:
        def __init__(self):
            self.claim_attempts = 0

        async def list_due(self, *, now_ms):
            _ = now_ms
            return [_outbox_row(_intent())]

        async def begin_delivery_attempt(self, row_id):
            assert row_id == 7
            self.claim_attempts += 1
            raise RuntimeError("outbox claim unavailable")

    external = _External()
    outbox = _FailingClaimOutbox()
    service = _service(
        ResolvedTargets(None, _ext_target()),
        GovernorVerdict.PUSH_NOW,
        external=external,
        outbox=outbox,
        log=_Log(),
    )

    await service.drain_due(now_ms=1000)

    assert outbox.claim_attempts == 1
    assert external.pushes == []


@pytest.mark.asyncio
async def test_submit_desktop_failure_does_not_block_external_push():
    class _FailingDesktop:
        async def write(self, intent, body): raise RuntimeError("desktop down")
    external, log = _External(), _Log()
    svc = _service(ResolvedTargets("s1", _ext_target()), GovernorVerdict.PUSH_NOW,
                   desktop=_FailingDesktop(), external=external, log=log)
    with pytest.raises(
        RuntimeError,
        match="desktop completion was not persisted",
    ):
        await svc.submit(_intent())
    assert external.pushes
    assert log.records


@pytest.mark.asyncio
async def test_submit_drop_persists_then_closes_external_intent():
    external, outbox, log = _External(), _Outbox(), _Log()
    svc = _service(ResolvedTargets("s1", _ext_target()), GovernorVerdict.DROP,
                   external=external, outbox=outbox, log=log)
    await svc.submit(_intent())
    assert not external.pushes and len(outbox.enqueued) == 1 and not log.records
    assert outbox.statuses == [(1, "dropped")]


@pytest.mark.asyncio
async def test_drain_external_none_marks_dropped():
    class _DrainOutbox:
        def __init__(self): self.marked = []
        async def list_due(self, *, now_ms):
            return [_outbox_row(_intent(), row_id=9)]
        async def mark_status(self, row_id, status): self.marked.append((row_id, status))
    external, outbox = _External(), _DrainOutbox()
    svc = _service(ResolvedTargets(None, None), GovernorVerdict.PUSH_NOW,
                   external=external, outbox=outbox)
    await svc.drain_due(now_ms=1000)
    assert not external.pushes and outbox.marked == [(9, "dropped")]


@pytest.mark.asyncio
async def test_drain_bad_json_marks_dropped():
    class _DrainOutbox:
        def __init__(self): self.marked = []
        async def list_due(self, *, now_ms):
            return [{"id": 11, "intent_json": "{not valid json", "release_at_ms": 1}]
        async def mark_status(self, row_id, status): self.marked.append((row_id, status))
    external, outbox = _External(), _DrainOutbox()
    svc = _service(ResolvedTargets("s1", _ext_target()), GovernorVerdict.PUSH_NOW,
                   external=external, outbox=outbox)
    await svc.drain_due(now_ms=1000)
    assert not external.pushes and outbox.marked == [(11, "dropped")]
