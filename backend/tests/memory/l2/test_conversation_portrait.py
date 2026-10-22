"""Conversation self-reports retain source roles and authored evidence end to end."""

import json

import pytest
from magi_plugin_sdk import (
    ExtractionProfileSpec,
    HistoryImportParseResult,
    HistoryImportRecord,
    HistoryImportSource,
    HistoryImporterSpec,
)

from magi.memory.history_imports.service import HistoryImportService
from magi.memory.history_imports.store import HistoryImportStore
from magi.plugins.history_importers import HistoryImporterRegistry
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from memory.l2 import test_personal_document_portrait as documents

_SOURCES = ["codex_agent_history", "claude_code_agent_history"]
_EXCLUDED = {
    "行内": "`我叫行内。`",
    "代码": "```text\n我叫代码。\n```",
    "缩进": "    我叫缩进。",
    "引用": "<blockquote>我叫引用。</blockquote>",
    "转录": "Assistant: 我叫转录。",
    "延续": "> 引用开始\n我叫延续。",
}


def _profiles():
    return [
        ExtractionProfileSpec(
            profile_id=f"source.{source}",
            source_types=[source],
            allowed_entity_types="all",
            allowed_predicates="all",
            structured_allowed_entity_types=["project", "software", "topic"],
            structured_allowed_predicates=["USES", "REFERENCES"],
            allow_assertion=True,
        )
        for source in _SOURCES
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("ingress", ["chat", "history_import", *_SOURCES])
async def test_explicit_user_facts_reach_portrait_but_other_roles_and_quotes_do_not(
    tmp_path, monkeypatch, ingress
):
    content = documents._NOTE + "\n\n" + "\n\n".join(_EXCLUDED.values())
    if ingress in _SOURCES:
        content = "## User turn 1\n\n" + content + "\n\n## User turn 2\n\n好的。"
    payload = documents._payload()
    for name in [*_EXCLUDED, "助手", "工具"]:
        payload["fact_claims"].append(
            {
                **payload["fact_claims"][0],
                "object_ref": name,
                "evidence_text": f"我叫{name}。",
            }
        )
    # Even a model that labels quoted entities as authored must fail grounding.
    payload["entities"].append(
        {
            **payload["entities"][0],
            "surface": "行内",
            "normalized_name": "行内",
            "entity_type": "person",
            "resolved_id": None,
            "is_new": True,
        }
    )
    monkeypatch.setattr(documents, "_profiles", _profiles)
    adapter = documents._QualityAdapter(payload)
    memory = await documents._memory(tmp_path, adapter)
    service = None
    try:
        for ref, name, kind in [
            ("group:diiv", "DIIV", "group"),
            ("food:coffee", "咖啡", "food"),
            ("person:alice", "Alice", "person"),
        ]:
            await memory.l2_entity_catalog.upsert_entity(
                entity_id=ref, canonical_name=name, entity_type=kind
            )
        if ingress == "history_import":

            class Importer:
                async def parse(self, paths):
                    return HistoryImportParseResult(
                        sources=[
                            HistoryImportSource(
                                source_id="conversation",
                                source_name="Conversation",
                                session_key="session",
                                records=[
                                    HistoryImportRecord(
                                        message_key=str(index),
                                        source_order=index,
                                        speaker_id=role,
                                        speaker_name=role,
                                        role_hint=role,
                                        content=text,
                                        occurred_at=1_790_000_000.0 + index,
                                        timestamp_confidence="exact",
                                    )
                                    for index, (role, text) in enumerate(
                                        [
                                            ("other", "我叫工具。"),
                                            ("assistant", "我叫助手。"),
                                            ("user", content),
                                        ]
                                    )
                                ],
                            )
                        ]
                    )

            registry = HistoryImporterRegistry()
            registry.register(
                connection_id="archive",
                plugin_id="archive",
                importer_id="export",
                importer=Importer(),
                spec=HistoryImporterSpec(
                    importer_id="export",
                    display_name="Archive",
                    accepted_extensions=["json"],
                    format_version="1",
                ),
            )
            service = HistoryImportService(
                store=HistoryImportStore(db_path=memory.memory_db_path),
                memory=memory,
                importer_registry=registry,
            )
            path = tmp_path / "export.json"
            path.write_text("{}")
            preview = await service.preview_importer_paths(
                connection_id="archive",
                plugin_id="archive",
                importer_id="export",
                paths=[str(path)],
            )
            assert [item.display_name for item in preview.participants] == ["user"]
            await service.confirm(
                job_id=preview.job_id,
                included_source_ids=preview.source_ids,
                confirm_personal_writing=False,
                self_participant_ids=[preview.participants[0].participant_id],
            )
            await documents._wait_for_import_and_l2(service, memory, job_id=preview.job_id)
            assert any(
                "[ASSISTANT]" in line and "我叫助手。" in line
                for line in adapter.calls[0]["prompt"].splitlines()
            )
        elif ingress == "chat":
            from magi.events.events import EventLevel, EventTypes

            await memory.ingest_event(
                {
                    "id": "chat-user",
                    "type": EventTypes.USER_MESSAGE,
                    "source": "chat",
                    "timestamp": 1_790_000_000.0,
                    "level": EventLevel.INFO.value,
                    "data": {"user_id": "local_user", "session_id": "chat", "content": content},
                }
            )
            await documents._wait(memory)
        else:
            await memory.ingest_event(documents._source_event(ingress, content))
            await documents._wait(memory)
        assert documents._NAME in adapter.calls[0]["prompt"]
        assert all(text not in adapter.calls[0]["prompt"] for text in _EXCLUDED.values())
        claims = await memory.l2.list_grounded_claims(user_id="local_user")
        assert len(claims) == 6
        assert await memory.l2_entity_catalog.find_by_canonical_name("行内") == []
        assert {row["object_value"] for row in claims}.isdisjoint(
            {*_EXCLUDED, "助手", "工具", "苏眠", "爵士乐", "画画", "游泳"}
        )
        name = next(row for row in claims if row["object_value"] == "明日香")
        evidence = (await memory.l2.get_grounded_claim(name["claim_id"]))["evidence"][0]
        locator = evidence["evidence_locator"]
        assert evidence["author_type"] == "user"
        assert locator["attribution"] == "author_prose"
        assert locator["start"] == content.rindex(documents._NAME)
        assert content[locator["start"] : locator["end"]] == documents._NAME
        assert (
            next(row for row in claims if row["object_value"] == "food:coffee")["polarity"]
            == "negative"
        )
        assert (
            next(row for row in claims if row["object_value"] == "艾琳")["subject_ref"]
            == "person:alice"
        )
        assertions = await memory.l2.list_current_assertions(
            entity_id="user:local_user", committed_only=False
        )
        assert {row["trait_name"] for row in assertions} == {
            "identity.real_name",
            "communication.address.preferred",
            "preference.affinity",
        }
        portrait = await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        assert "尚未形成长期结论" in " ".join(portrait.prompt_summary)
        for assertion in assertions:
            await memory.l2.apply_user_feedback(
                assertion_id=assertion["assertion_id"], feedback="confirmed"
            )
        portrait = await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        rendered = json.dumps(
            {"world": portrait.world, "recent": portrait.recent, "prompt": portrait.prompt_summary},
            ensure_ascii=False,
        )
        for expected in ["明日香", "小明", "DIIV"]:
            assert expected in rendered
        for excluded in [
            *_EXCLUDED,
            "助手",
            "工具",
            "艾琳",
            "苏眠",
            "爵士乐",
            "画画",
            "游泳",
            "2099",
            "咖啡",
        ]:
            assert excluded not in rendered
    finally:
        if service:
            await service.stop()
        await memory.shutdown()
