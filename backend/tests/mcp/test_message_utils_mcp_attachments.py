"""Verify _build_latest_user_message_content emits MCP resource blocks."""

from magi.agent.message_utils import append_latest_user_message
from magi.agent.execution.attachment_resolver import NullAttachmentResolver
from magi.agent.turn_input import UserTurnInput

_NULL_RESOLVER = NullAttachmentResolver()


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
        resolver=_NULL_RESOLVER,
        history_token_budget=None,
    )
    assert len(messages) == 1
    content = messages[0]["content"]
    # When every block is text (user text + mcp resource text block),
    # _build_latest_user_message_content collapses them into a single
    # "\n\n"-joined string rather than a multi-block list.
    assert isinstance(content, str)
    assert "please summarize" in content
    assert "<mcp_resource" in content and "# Hello" in content


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
        resolver=_NULL_RESOLVER,
        history_token_budget=None,
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
        resolver=_NULL_RESOLVER,
        history_token_budget=None,
    )
    # Missing image is silently skipped; user text returned as plain string.
    assert messages[0]["content"] == "look"
