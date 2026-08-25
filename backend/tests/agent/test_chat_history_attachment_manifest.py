from __future__ import annotations

from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.chat.read.models import ChatDisplayMessage


def test_session_attachment_manifest_keeps_attachment_ids_visible() -> None:
    manifest = ChatContextAssembler._build_session_attachment_manifest(
        [
            ChatDisplayMessage(
                role="user",
                content="看这个报告",
                timestamp=1,
                kind="user",
                turn_id="turn-1",
                attachments=[
                    {
                        "attachment_id": "att-report",
                        "kind": "pdf",
                        "original_name": "report.pdf",
                        "parse_status": "parsed",
                        "page_count": 28,
                        "character_count": 14355,
                    }
                ],
            )
        ]
    )

    assert manifest is not None
    assert "read_chat_attachment" in manifest
    assert "attachment_id=att-report" in manifest
    assert "name=report.pdf" in manifest
    assert "pages=28" in manifest
    assert "chars=14355" in manifest
    assert "turn_id=turn-1" in manifest

    summary = ChatContextAssembler._combine_session_summaries(manifest)

    assert summary is not None
    assert "# Session Attachment References" in summary
    assert "attachment_id=att-report" in summary


def test_session_attachment_manifest_keeps_newest_references() -> None:
    messages = [
        ChatDisplayMessage(
            role="user",
            content=f"file {index}",
            timestamp=index,
            kind="user",
            turn_id=f"turn-{index}",
            attachments=[
                {
                    "attachment_id": f"att-{index}",
                    "kind": "text_file",
                    "original_name": f"file-{index}.txt",
                }
            ],
        )
        for index in range(42)
    ]

    manifest = ChatContextAssembler._build_session_attachment_manifest(messages)

    assert manifest is not None
    assert "- attachment_id=att-0;" not in manifest
    assert "- attachment_id=att-1;" not in manifest
    assert "- attachment_id=att-2;" in manifest
    assert "- attachment_id=att-41;" in manifest
    assert "2 older attachment reference(s) omitted" in manifest
