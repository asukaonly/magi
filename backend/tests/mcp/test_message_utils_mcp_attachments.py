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


def test_unresolved_attachments_preserve_user_text():
    for attachment in [
        {"kind": "mcp_resource", "server_id": "docs", "uri": "u", "resolved_error": "broken"},
        {"kind": "image", "storage_path": "/tmp/does-not-exist.png"},
    ]:
        messages = append_latest_user_message(
            history=[],
            turn=UserTurnInput(text="hi", attachments=[attachment]),
            resolver=_NULL_RESOLVER,
            history_token_budget=None,
        )
        assert messages == [{"role": "user", "content": "hi"}]
