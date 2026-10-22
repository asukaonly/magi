"""Explicit review stub for tests focused on downstream storage, not semantics."""

import json

from magi.memory.l2.self_report_review import SELF_REPORT_REVIEW_PROMPT


def supported_review_response(kwargs):
    messages = kwargs.get("messages", [])
    if not any(message.get("content") == SELF_REPORT_REVIEW_PROMPT for message in messages):
        return None
    data = json.loads(messages[-1]["content"])
    return json.dumps(
        {
            "reviews": [
                {"claim_index": candidate["claim_index"], "verdict": "supported"}
                for candidate in data["candidates"]
            ]
        }
    )
