"""Preserve user-owned builtin personas during bundle updates."""

import hashlib
import json

from alembic import op

revision = "v4"
down_revision = "v3"
branch_labels = None
depends_on = None

# Frozen seeded row values from the v1 schema baseline through v3. Include the
# editable registry columns so even a metadata-only edit is preserved.
_SHIPPED_SEEDS = {
    # en/ember
    "994b6a1b460b5ce539985b8a611a1c4131c2e94b0f0a94043a68f1f504fb2971",
    "80b721f8cdcd8860d66f628eb95ecb9a6bccee526b2596d08c89e901e3d65db2",
    "730c151dda48c467527828fb89695069465971a1247ea16ae64504bdfacb7f66",
    # en/halberd
    "df12372d6250d9070dd265789e8f9c7a0cab3dfcbf24592166e770f98e6f275f",
    "121282f2f331f5762b3a0e46a54c49a5a8778a3c38806a0312dcf985c02a9ddb",
    "42ff265a7405070180613e93add9d9e6ccc69b68b22f7e478440ac93e2b37770",
    # en/jinx_hacker
    "3cf52e8e752c639c7490ea93c9f5af78d0115c41b5bb1d50253ed6ab99bbf5a0",
    "a22a8890a4935fc206f0c272bf19e67273b56fe352fa5a3397e5a2454c8d160d",
    "22bd3bcc540860a100a8875f93a97c01f05a3013bceaef1f204ef07d6f5dced7",
    # en/nova_assistant
    "2e26adc15220146e3d5cf76e8ac952175c5d76cafb7534b41eb42f13f5a7fb46",
    "b5329ede237028f802de0ea00b18472923bb3fe2f8e343562129c6e075469547",
    "2964efb8e3676621a7dff7363a786f0bc4a49b5fc03f254ed30d22be3624f2f8",
    # zh/echo_ai_assistant
    "78e35a45ee0172b96bf2c1838d5a27a214bc48b68b1751278d900d2d1c285449",
    "b17ccbfdfacde1c8306e1fd34d0f25b965719f786b2dff1b8c89c9e3616f1eed",
    "a51a4e3dc7fc47cf5561cce6e7469e5ba1ea40ae486b644f5e54fbd1342846b4",
    # zh/seven_hacker
    "3f06269780c4a180d6032dccef1116ae395711f87cf28f68b1df4f0f429a48a7",
    "31657d53b917b399ef980193173c6aeb144c6da6e68047b4d3c4e14b24f477db",
    "53e834f38e88904bbf03d83a03de256a9cc1bbfdc5cf6d0daefecc516bd3a69e",
    "c96ccf41ac4ce8ae19a1ebd9668020444f7140b1ab907de8289c6a471b28098e",
    "55e101e3a42c63c5e0b7c6bd913ec5c47bf454ce7d6590e82ecfc30392d26de3",
    # zh/sichen
    "79cac1956a5321c4a3063c5aca4b4a248184ec0d23091cd5bd81065c6be365ce",
    "eb4fc73956f57eb6ffead746c5cce49b7c93b2406aba1c681029b27fc2dc1af9",
    "c008e3a9e955da2a61eda42227e90622c4dd2244f59736012c146a4bb3c0d05f",
    # zh/sumen_listener
    "d2f712e0f3350a34f9b898cfef61a1d423113ce7228f0ff2a74cf0a43997af62",
    "213750ed27ac95263b0cd37599f65899f1ea848e191a20c7fcdcb847324b6a7b",
    "b527fd638356943de08e406b3465de70a5c4a98a509e8095baa5eab62fa15a86",
}


def upgrade() -> None:
    db = op.get_bind()
    columns = {row[1] for row in db.exec_driver_sql("PRAGMA table_info(personas)")}
    if "seed_user_modified" not in columns:
        db.exec_driver_sql(
            "ALTER TABLE personas ADD COLUMN seed_user_modified INTEGER NOT NULL DEFAULT 0"
        )
    rows = db.exec_driver_sql(
        """SELECT persona_id, locale, seed_slug, slug, name, config_json, avatar_path,
                  group_name, sort_order, description FROM personas WHERE is_builtin = 1"""
    ).fetchall()
    for persona_id, *fields in rows:
        snapshot = json.dumps(fields, ensure_ascii=False).encode("utf-8")
        if hashlib.sha256(snapshot).hexdigest() not in _SHIPPED_SEEDS:
            db.exec_driver_sql("UPDATE personas SET seed_user_modified = 1 WHERE persona_id = ?", (persona_id,))


def downgrade() -> None:
    op.execute("ALTER TABLE personas DROP COLUMN seed_user_modified")
