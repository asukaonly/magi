import pytest
from magi.outreach.contracts import OutreachIntent, OutreachKind, Urgency, ResolvedTargets, GovernorVerdict
from magi.outreach.service import OutreachService
from magi_plugin_sdk.channels import ChannelTarget


def _intent(urgency=Urgency.NORMAL):
    return OutreachIntent(kind=OutreachKind.TASK_COMPLETED, user_id="u1",
                          origin_session_id="s1", title="t", facts="f",
                          correlation_id="c1", completed_at_ms=1, urgency=urgency)


def _ext_target():
    return ChannelTarget(channel_type="telegram", external_chat_id="X1",
                         magi_session_id="s1", magi_user_id="u1")


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
    async def push(self, intent, body, *, target): self.pushes.append((intent, body, target)); return ["r"]


class _Outbox:
    def __init__(self): self.enqueued = []
    async def enqueue(self, *, intent_json, release_at_ms, created_at_ms):
        self.enqueued.append((intent_json, release_at_ms)); return 1


class _Log:
    def __init__(self): self.records = []
    async def record(self, **kw): self.records.append(kw)


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
    desktop, external, log = _Desktop(), _External(), _Log()
    svc = _service(ResolvedTargets("s1", _ext_target()), GovernorVerdict.PUSH_NOW,
                   desktop=desktop, external=external, log=log)
    await svc.submit(_intent())
    assert desktop.writes and desktop.writes[0][1] == "magi-voiced body"
    assert external.pushes and external.pushes[0][1] == "magi-voiced body"
    assert log.records and log.records[0]["correlation_id"] == "c1"


@pytest.mark.asyncio
async def test_submit_desktop_origin_only():
    desktop, external = _Desktop(), _External()
    svc = _service(ResolvedTargets("s1", None), GovernorVerdict.PUSH_NOW,
                   desktop=desktop, external=external)
    await svc.submit(_intent())
    assert desktop.writes and not external.pushes


@pytest.mark.asyncio
async def test_submit_defer_enqueues_outbox_not_push():
    external, outbox = _External(), _Outbox()
    svc = _service(ResolvedTargets("s1", _ext_target()), GovernorVerdict.DEFER, release=999,
                   external=external, outbox=outbox)
    await svc.submit(_intent())
    assert not external.pushes
    assert outbox.enqueued and outbox.enqueued[0][1] == 999


@pytest.mark.asyncio
async def test_drain_due_pushes_and_marks_delivered():
    import json
    external, log = _External(), _Log()

    class _DrainOutbox:
        def __init__(self): self.marked = []
        async def list_due(self, *, now_ms):
            return [{"id": 7, "intent_json": json.dumps(_intent().to_dict()), "release_at_ms": 1}]
        async def mark_status(self, row_id, status): self.marked.append((row_id, status))

    outbox = _DrainOutbox()
    svc = _service(ResolvedTargets(None, _ext_target()), GovernorVerdict.PUSH_NOW,
                   external=external, outbox=outbox, log=log)
    await svc.drain_due(now_ms=1000)
    assert external.pushes and outbox.marked == [(7, "delivered")]
