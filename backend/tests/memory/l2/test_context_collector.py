from __future__ import annotations

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _build_user_message(text: str):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "web_user",
                "session_id": "s1",
                "content": text,
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="corr-context",
        ),
        event_id="evt-context",
    )


def test_context_bundle_and_refs_serialize_deterministically():
    from magi.memory.l2.context_bundle import ContextBundle, ContextEntity, ResolvedContextRef

    bundle = ContextBundle(
        recent_messages=[{"event_id": "evt-1", "content": "杭州天气怎么样"}],
        recent_entities=[{"entity_id": "food:west-lake-vinegar-fish", "surface": "西湖醋鱼", "entity_type": "food"}],
        live_context_entities=[
            ContextEntity(
                context_id="weather_state:hangzhou-rainy-11c",
                kind="weather_state",
                summary="杭州，阵雨，11度",
                payload={"condition": "rainy", "temperature_c": 11},
                source_event_ids=["evt-weather-1"],
                created_at=1710000000.0,
                expires_at=1710007200.0,
            )
        ],
        pronoun_bindings=[{"surface": "我", "resolved_ref": "user:self", "resolved_kind": "self_actor"}],
        source_event_ids=["evt-1", "evt-weather-1"],
    )
    ref = ResolvedContextRef(
        surface="这种天气",
        reference_type="context_entity",
        resolved_ref="weather_state:hangzhou-rainy-11c",
        resolved_kind="weather_state",
        confidence=0.91,
        evidence_text="我真的很烦这种天气耶",
    )

    assert bundle.to_dict() == {
        "recent_messages": [{"event_id": "evt-1", "content": "杭州天气怎么样"}],
        "recent_entities": [{"entity_id": "food:west-lake-vinegar-fish", "surface": "西湖醋鱼", "entity_type": "food"}],
        "live_context_entities": [
            {
                "context_id": "weather_state:hangzhou-rainy-11c",
                "kind": "weather_state",
                "summary": "杭州，阵雨，11度",
                "payload": {"condition": "rainy", "temperature_c": 11},
                "source_event_ids": ["evt-weather-1"],
                "created_at": 1710000000.0,
                "expires_at": 1710007200.0,
            }
        ],
        "pronoun_bindings": [{"surface": "我", "resolved_ref": "user:self", "resolved_kind": "self_actor"}],
        "source_event_ids": ["evt-1", "evt-weather-1"],
    }
    assert ref.to_dict() == {
        "surface": "这种天气",
        "reference_type": "context_entity",
        "resolved_ref": "weather_state:hangzhou-rainy-11c",
        "resolved_kind": "weather_state",
        "confidence": 0.91,
        "evidence_text": "我真的很烦这种天气耶",
    }


def test_collect_context_bundle_binds_self_pronoun():
    from magi.memory.l2.context_collector import collect_context_bundle, resolve_direct_context_refs

    event = _build_user_message("我真的很烦这种天气耶")

    bundle = collect_context_bundle(event=event)
    refs = resolve_direct_context_refs(event=event, bundle=bundle)

    assert bundle.pronoun_bindings == [{"surface": "我", "resolved_ref": "web_user", "resolved_kind": "self_actor"}]
    assert refs[0].to_dict() == {
        "surface": "我",
        "reference_type": "self_actor",
        "resolved_ref": "web_user",
        "resolved_kind": "self_actor",
        "confidence": 1.0,
        "evidence_text": "我真的很烦这种天气耶",
    }


def test_collect_context_bundle_binds_single_weather_slot_for_zhezhong_tianqi():
    from magi.memory.l2.context_bundle import ContextEntity
    from magi.memory.l2.context_collector import collect_context_bundle, resolve_direct_context_refs

    event = _build_user_message("我真的很烦这种天气耶")
    bundle = collect_context_bundle(
        event=event,
        live_context_entities=[
            ContextEntity(
                context_id="weather_state:hangzhou-rainy-11c",
                kind="weather_state",
                summary="杭州，阵雨，11度",
                payload={"condition": "rainy"},
                source_event_ids=["evt-weather-1"],
                created_at=1710000000.0,
                expires_at=1710007200.0,
            )
        ],
    )

    refs = resolve_direct_context_refs(event=event, bundle=bundle)

    assert any(ref.surface == "这种天气" and ref.resolved_ref == "weather_state:hangzhou-rainy-11c" for ref in refs)


def test_collect_context_bundle_binds_most_recent_food_for_zhedao_cai():
    from magi.memory.l2.context_collector import collect_context_bundle, resolve_direct_context_refs

    event = _build_user_message("这道菜我不喜欢")
    bundle = collect_context_bundle(
        event=event,
        recent_entities=[
            {"entity_id": "food:sushi", "surface": "寿司", "entity_type": "food"},
            {"entity_id": "food:west-lake-vinegar-fish", "surface": "西湖醋鱼", "entity_type": "food"},
        ],
    )

    refs = resolve_direct_context_refs(event=event, bundle=bundle)

    assert any(ref.surface == "这道菜" and ref.resolved_ref == "food:west-lake-vinegar-fish" for ref in refs)


def test_collect_context_bundle_returns_unresolved_when_multiple_weather_slots_exist():
    from magi.memory.l2.context_bundle import ContextEntity
    from magi.memory.l2.context_collector import collect_context_bundle, resolve_direct_context_refs

    event = _build_user_message("我真的很烦这种天气耶")
    bundle = collect_context_bundle(
        event=event,
        live_context_entities=[
            ContextEntity(
                context_id="weather_state:hangzhou-rainy-11c",
                kind="weather_state",
                summary="杭州，阵雨，11度",
                payload={"condition": "rainy"},
                source_event_ids=["evt-weather-1"],
                created_at=1710000000.0,
                expires_at=1710007200.0,
            ),
            ContextEntity(
                context_id="weather_state:shanghai-cloudy-9c",
                kind="weather_state",
                summary="上海，多云，9度",
                payload={"condition": "cloudy"},
                source_event_ids=["evt-weather-2"],
                created_at=1710000000.0,
                expires_at=1710007200.0,
            ),
        ],
    )

    refs = resolve_direct_context_refs(event=event, bundle=bundle)

    assert not any(ref.surface == "这种天气" for ref in refs)
