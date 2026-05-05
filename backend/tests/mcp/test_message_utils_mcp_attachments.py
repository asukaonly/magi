"""Verify _build_latest_user_message_content emits MCP resource blocks."""

from magi.agent.message_utils import append_latest_user_message
from magi.agent.turn_input import UserTurnInput


def test_mcp_resource_emits_text_block():
    messages = append_latest_user_message(
        history=[],
        turn=UserTurnInput(
            text="please summarize",
            attachments=[
                {
                    "kind": "mcp_resource",
                    "server_id": "docs",
                    "uri": "file:///readme.md",
                    "resolved_text": (
                        '<mcp_resource server_id="docs" uri="file:///readme.md" '
                        'mimeType="text/markdown">\n# Hello\n</mcp_resource>'
                    ),
                }
            ],
        ),
    )
    assert len(messages) == 1
    content = messages[0]["content"]
    # Multi-block content (text + mcp text block) is returned as a list
    assert isinstance(content, list)
    texts = [b["text"] for b in content if b["type"] == "text"]
    assert "please summarize" in texts
    assert any("<mcp_resource" in t and "# Hello" in t for t in texts)


def test_mcp_resource_without_resolved_text_is_silent():
    messages = append_latest_user_message(
        history=[],
        turn=UserTurnInput(
            text="hi",
            attachments=[
                {
                    "kind": "mcp_resource",
                    "server_id": "docs",
                    "uri": "u",
                    "resolved_error": "broken",
                }
            ],
        ),
    )
    # User text only — no resolved_text means no extra block.
    assert messages[0]["content"] == "hi"


def test_image_path_still_works():
    """Sanity check that the image branch wasn't broken by the refactor."""
    messages = append_latest_user_message(
        history=[],
        turn=UserTurnInput(
            text="look",
            attachments=[
                {"kind": "image", "storage_path": "/tmp/does-not-exist.png"},
            ],
        ),
    )
    # Missing image is silently skipped; user text returned as plain string.
    assert messages[0]["content"] == "look"
