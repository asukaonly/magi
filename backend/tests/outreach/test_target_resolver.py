import pytest
from types import SimpleNamespace
from magi.outreach.contracts import OutreachIntent, OutreachKind
from magi.outreach.target_resolver import TargetResolver


def _intent(session_id="s1"):
    return OutreachIntent(
        kind=OutreachKind.TASK_COMPLETED, user_id="u1", origin_session_id=session_id,
        title="t", facts="f", correlation_id="c1", completed_at_ms=1,
    )


class _ReadService:
    def __init__(self, exists: bool, *, fail: bool = False):
        self._exists = exists
        self._fail = fail

    async def aget_session_summary(self, user_id, session_id):
        if self._fail:
            raise OSError("chat database unavailable")
        return SimpleNamespace(session_id=session_id) if self._exists else None


class _Mapper:
    def __init__(self, mapping, *, fail: bool = False):
        self._mapping = mapping
        self._fail = fail

    async def lookup_by_session(self, magi_session_id):
        if self._fail:
            raise OSError("channel database unavailable")
        return self._mapping


def _mapping(channel_type, external_chat_id="X1"):
    return SimpleNamespace(channel_type=channel_type, external_chat_id=external_chat_id, magi_user_id="u1")


@pytest.mark.asyncio
async def test_external_origin_yields_desktop_and_external():
    r = TargetResolver(read_service_factory=lambda: _ReadService(True),
                       session_mapper=_Mapper(_mapping("telegram")))
    out = await r.resolve(_intent())
    assert out.desktop_session_id == "s1"
    assert out.external is not None and out.external.channel_type == "telegram"
    # external_chat_id is intentionally "" — the channel resolves it from
    # magi_session_id at deliver time (see TargetResolver / delivery_prefs).
    assert out.external.external_chat_id == "" and out.external.magi_session_id == "s1"


@pytest.mark.asyncio
async def test_desktop_origin_yields_desktop_only():
    r = TargetResolver(read_service_factory=lambda: _ReadService(True),
                       session_mapper=_Mapper(_mapping("chat_sse")))
    out = await r.resolve(_intent())
    assert out.desktop_session_id == "s1"
    assert out.external is None


@pytest.mark.asyncio
async def test_deleted_session_skips_all_outreach_targets():
    r = TargetResolver(read_service_factory=lambda: _ReadService(False),
                       session_mapper=_Mapper(_mapping("telegram")))
    out = await r.resolve(_intent())
    assert out.desktop_session_id is None
    assert out.external is None


@pytest.mark.asyncio
async def test_failed_session_check_remains_retryable():
    r = TargetResolver(
        read_service_factory=lambda: _ReadService(False, fail=True),
        session_mapper=_Mapper(_mapping("telegram")),
    )
    with pytest.raises(OSError, match="chat database unavailable"):
        await r.resolve(_intent())


@pytest.mark.asyncio
async def test_failed_session_mapping_check_remains_retryable():
    r = TargetResolver(
        read_service_factory=lambda: _ReadService(True),
        session_mapper=_Mapper(None, fail=True),
    )
    with pytest.raises(OSError, match="channel database unavailable"):
        await r.resolve(_intent())
