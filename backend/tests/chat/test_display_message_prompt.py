from __future__ import annotations

from magi.chat.read.models import ChatDisplayMessage


def test_prompt_message_includes_attachment_references() -> None:
    message = ChatDisplayMessage(
        role="user",
        content="分析一下这个文档说了什么",
        timestamp=1,
        kind="user",
        attachments=[
            {
                "attachment_id": "att-report",
                "kind": "pdf",
                "original_name": "report.pdf",
                "page_count": 28,
                "character_count": 14355,
                "parse_status": "parsed",
                "storage_path": "/private/runtime/report.pdf",
            }
        ],
    )

    prompt_message = message.to_prompt_message()

    assert prompt_message["role"] == "user"
    assert "分析一下这个文档说了什么" in prompt_message["content"]
    assert "[Message attachment references]" in prompt_message["content"]
    assert "attachment_id=att-report" in prompt_message["content"]
    assert "name=report.pdf" in prompt_message["content"]
    assert "kind=pdf" in prompt_message["content"]
    assert "pages=28" in prompt_message["content"]
    assert "chars=14355" in prompt_message["content"]
    assert "parse_status=parsed" in prompt_message["content"]
    assert "storage_path" not in prompt_message["content"]
    assert "/private/runtime/report.pdf" not in prompt_message["content"]


def test_prompt_message_omits_attachment_block_without_attachment_ids() -> None:
    message = ChatDisplayMessage(
        role="assistant",
        content="没有附件引用",
        timestamp=1,
        kind="assistant",
        attachments=[{"kind": "pdf", "original_name": "report.pdf"}],
    )

    prompt_message = message.to_prompt_message()

    assert prompt_message["content"] == "没有附件引用"