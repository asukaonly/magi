from __future__ import annotations

from magi.timeline.query_interpreter import TimelineQueryInterpreter


def test_query_interpreter_extracts_time_mood_and_activity_hints() -> None:
    interpreter = TimelineQueryInterpreter()

    interpretation = interpreter.interpret(
        query="上周 低落 游戏",
        start=0.0,
        end=14 * 24 * 60 * 60.0,
    )

    assert interpretation.start == (14 - 7) * 24 * 60 * 60.0
    assert interpretation.end == 14 * 24 * 60 * 60.0
    assert interpretation.mood_hints == ["low"]
    assert interpretation.activity_hints == ["game"]
    assert "game" in interpretation.search_terms
