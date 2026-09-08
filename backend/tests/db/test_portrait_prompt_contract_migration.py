"""Old portrait prompts become ineligible without modifying retained facts or cache text."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_portrait_prompt_contract_upgrade_invalidates_derived_caches_only(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, path)
    command.upgrade(config, "v50_profile_fact_descriptions")
    summary = json.dumps(["用户关注或偏好：这条记录缺少完整事实描述。"], ensure_ascii=False)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "INSERT INTO user_portrait_projection (user_id, entity_id, prompt_summary_json, generated_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("audit", "user:audit", summary, 1.0, 2.0, 3.0),
        )
        db.execute(
            """
            INSERT INTO user_profile_projection (
                user_id, entity_id, preferred_form_of_address, refreshed_at, created_at, updated_at
            ) VALUES ('audit', 'user:audit', '小林', 1, 2, 3)
            """
        )
        db.execute(
            """
            INSERT INTO tom_trait_assertions (
                assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                confidence_score, evidence_events, volatility_index, source_domain,
                inference_depth, validation_state, first_inferred_at, last_validated_at,
                target_entity_id, target_entity_type, target_scope, temporal_scope,
                natural_summary, status, created_at, updated_at, slot_key, claim_fingerprint
            ) VALUES (
                'address', 'user:audit', 'user', 'communication_profile',
                'communication.address.preferred', ?, 0.8, '["event-1"]', 0.1,
                'settings_profile', 'explicit', 'tentative', 10, 20, '', '', 'global', 'stable',
                '用户希望保留完整称呼。', 'tentative', 10, 20, 'slot:address', 'claim:address'
            )
            """,
            (json.dumps(["小林", "老板"], ensure_ascii=False),),
        )
        before = dict(db.execute("SELECT * FROM user_portrait_projection").fetchone())
        assertion_before = dict(db.execute("SELECT * FROM tom_trait_assertions").fetchone())
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        after = dict(db.execute("SELECT * FROM user_portrait_projection").fetchone())
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "v53_gateway_read_indexes"
        assert db.execute("SELECT COUNT(*) FROM user_profile_projection").fetchone()[0] == 0
        assert dict(db.execute("SELECT * FROM tom_trait_assertions").fetchone()) == assertion_before
    assert after == {**before, "prompt_contract_version": 0}
    command.downgrade(config, "v50_profile_fact_descriptions")
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert dict(db.execute("SELECT * FROM user_portrait_projection").fetchone()) == before
        assert db.execute("SELECT COUNT(*) FROM user_profile_projection").fetchone()[0] == 0
        assert dict(db.execute("SELECT * FROM tom_trait_assertions").fetchone()) == assertion_before
