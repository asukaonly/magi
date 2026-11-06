from unittest.mock import AsyncMock

import pytest

from magi.timeline.cluster_builder import TimelineClusterBuilder
from magi.timeline.context_bundle_builder import TimelineContextBundleBuilder
from magi.timeline.presentation_text import authored_excerpt, readable_label


@pytest.mark.parametrize("label", ["entity:52b5f111f", "site:x.com, user", "codex agent history"])
def test_internal_labels_are_not_display_titles(label):
    assert not readable_label(label)


def test_authored_examples_are_preserved():
    assert authored_excerpt("Explain <environment_context> please") == "Explain <environment_context> please"
    text = "```xml\n<environment_context>\nexample\n</environment_context>\n```"
    assert authored_excerpt(text) == text


async def test_complete_membership_and_visible_pinned_prompts():
    records = {
        "a": {"event_id": "a", "source": "codex_agent_history", "content": "Codex conversed <environment_context>"},
        "b": {"event_id": "b", "source": "chrome_history", "content": "Chrome Browsing Page", "metadata": {
            "activity_snapshot": {"title": "Chrome Browsing · Page", "provenance": {"merged_visit_count": 2}, "content_blocks": [
                {"kind": "text", "value": "https://example.com/page"},
            ]},
        }},
    }
    store = AsyncMock()
    store.get_user_visible_event.side_effect = lambda event_id: records.get(event_id)
    store.get_pinned_payloads.return_value = {"a": "## User turn 1\n\n<environment_context>\nsetup\n</environment_context>\n\n## User turn 2\n\nFix the parser."}
    bundle = await TimelineContextBundleBuilder(l1_store=store).build(anchor={
        "source_event_ids": ["a", "b", "hidden", "a"], "representative_event_ids": ["a"],
    })
    assert [item["event_id"] for item in bundle["l1_events"]] == ["a", "b"]
    assert bundle["l1_events"][0]["summary"] == "Fix the parser."
    assert bundle["l1_events"][0]["user_prompts"] == ["Fix the parser."]
    assert bundle["l1_events"][1]["title"] == "Page"
    assert bundle["l1_events"][1]["url"] == "https://example.com/page"
    assert bundle["l1_events"][1]["visit_count"] == 2
    store.get_pinned_payloads.assert_awaited_once_with(["a"])


def test_transient_cluster_keeps_all_members_beyond_previews():
    events = [{"event_id": str(i), "timestamp": i, "source": "chrome_history",
               "metadata": {"activity_snapshot": {"tags": ["reading"]}}} for i in range(12)]
    cluster = TimelineClusterBuilder().build(events, scale="day")[0]
    assert len(cluster["representative_event_ids"]) == 3
    assert cluster["source_event_ids"] == [str(i) for i in range(12)]
