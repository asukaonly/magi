"""Retained fact wording survives the profile diagnostic cleanup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_profile_description_upgrade_only_removes_exact_diagnostics(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, path)
    command.upgrade(config, "v49_l4_strategy_revisions")
    diagnostic = "User profile field communication.address.preferred was set from personal profile settings."
    summaries = {
        "diagnostic": ("settings_profile", diagnostic),
        "retained_settings": ("settings_profile", "工作时请叫我小林；在家里叫小雨。"),
        "retained_preference": ("user_authored", "最近在工作时喜欢草莓和芒果，休息时不一定。"),
        "retained_goal": ("user_authored", "用户计划明年申请项目。 原文时间: 明年"),
        "retained_quote": ("conversation", "我以前喜欢草莓，现在不喜欢了。"),
        "other_source": ("user_authored", diagnostic),
        "extended_summary": ("settings_profile", diagnostic + " 用户希望被称为小林。"),
        "absent_summary": ("settings_profile", ""),
    }
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        for assertion_id, (source_domain, summary) in summaries.items():
            db.execute(
                """
                INSERT INTO tom_trait_assertions (
                    assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                    confidence_score, evidence_events, volatility_index, source_domain,
                    inference_depth, validation_state, first_inferred_at, last_validated_at,
                    target_entity_id, target_entity_type, target_scope, temporal_scope,
                    natural_summary, status, created_at, updated_at, slot_key, claim_fingerprint
                ) VALUES (
                    ?, 'user:local_user', 'user', 'communication_profile',
                    'communication.address.preferred', '小林', 0.8, '["event-1"]', 0.1,
                    ?, 'explicit', 'tentative', 10, 20, '', '', 'global', 'stable', ?,
                    'tentative', 10, 20, ?, ?
                )
                """,
                (assertion_id, source_domain, summary, f"slot:{assertion_id}", f"claim:{assertion_id}"),
            )
        before = {
            row["assertion_id"]: dict(row)
            for row in db.execute("SELECT * FROM tom_trait_assertions")
        }

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        after = {
            row["assertion_id"]: dict(row)
            for row in db.execute("SELECT * FROM tom_trait_assertions")
        }
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "v51_portrait_prompt_contract"

    expected = {key: dict(value) for key, value in before.items()}
    expected["diagnostic"]["natural_summary"] = ""
    assert after == expected

    command.downgrade(config, "v49_l4_strategy_revisions")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT natural_summary FROM tom_trait_assertions WHERE assertion_id = 'diagnostic'"
        ).fetchone() == ("",)
