from __future__ import annotations


def test_normalize_defaults_chattiness() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    out = normalize_generated_personality_payload({"idiolect": {"sentence_style": "x"}})
    assert out["idiolect"]["chattiness"] == 0.5


def test_normalize_clamps_chattiness() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    out = normalize_generated_personality_payload({"idiolect": {"chattiness": 9}})
    assert out["idiolect"]["chattiness"] == 1.0
    out2 = normalize_generated_personality_payload({"idiolect": {"chattiness": -3}})
    assert out2["idiolect"]["chattiness"] == 0.0
