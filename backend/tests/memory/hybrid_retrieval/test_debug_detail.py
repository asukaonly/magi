from __future__ import annotations

import logging

from magi.memory.hybrid_retrieval import debug_detail


def test_log_detail_omits_payload_when_full_content_logging_is_disabled(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(
        debug_detail,
        "full_content_logging_enabled",
        lambda: False,
    )
    logger = logging.getLogger("test.memory.debug_detail")

    with caplog.at_level(logging.INFO, logger=logger.name):
        debug_detail.log_detail(
            logger,
            "retrieval trace",
            {"content": "MEMORY-CONTENT-CANARY", "event_id": "event-1"},
        )

    rendered = caplog.text
    assert "MEMORY-CONTENT-CANARY" not in rendered
    assert "content" in rendered
    assert "event_id" in rendered
    assert "detail omitted by diagnostics setting" in rendered
