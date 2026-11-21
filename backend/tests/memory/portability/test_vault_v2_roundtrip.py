"""End-to-end tests for format-v2 full personal vault backup, ZIP64, Argon2id range, and rollback."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import zipfile
from pathlib import Path

import pytest

from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.crypto import (
    ENCRYPTED_BACKUP_MAGIC,
    _HEADER,
    _derive_key,
    decrypt_backup_payload,
)
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.preflight import inspect_memory_backup, load_restore_candidate
from magi.memory.portability.restore import ValidatedRestoreCandidate, prepare_memory_restore
from magi.memory.portability.storage import (
    create_memory_snapshot,
    discard_snapshot,
    vault_user_avatar_dir,
)
from magi.utils.runtime import RuntimePaths

_VAULT_TARGET_NAMES = {
    "l1",
    "memory_shared",
    "chat",
    "persona_registry",
    "growth_memory",
    "emotional",
    "personal_tasks",
}


def _migrate_full_vault(paths: RuntimePaths) -> None:
    selected = tuple(t for t in MIGRATION_TARGETS if t.name in _VAULT_TARGET_NAMES)
    run_upgrade_head(paths, targets=selected)


def _seed_full_vault(paths: RuntimePaths) -> dict[str, bytes]:
    _migrate_full_vault(paths)

    # 1. Manual entry image asset
    manual_bytes = b"manual-entry-photo-bytes"
    manual_digest = hashlib.sha256(manual_bytes).hexdigest()
    manual_asset_path = paths.manual_entry_assets_dir / manual_digest[:2] / f"{manual_digest}.png"
    manual_asset_path.parent.mkdir(parents=True, exist_ok=True)
    manual_asset_path.write_bytes(manual_bytes)

    # 2. Chat image attachment
    chat_img_bytes = b"chat-attached-image-bytes"
    chat_img_path = paths.chat_resources_dir / "images" / "session-1" / "photo.png"
    chat_img_path.parent.mkdir(parents=True, exist_ok=True)
    chat_img_path.write_bytes(chat_img_bytes)

    # 3. Custom user avatar
    avatar_bytes = b"custom-persona-avatar-bytes"
    avatar_path = vault_user_avatar_dir(paths) / "custom_companion.png"
    avatar_path.parent.mkdir(parents=True, exist_ok=True)
    avatar_path.write_bytes(avatar_bytes)

    # 4. Seed L1 + Memory
    with sqlite3.connect(paths.l1_memory_db_path) as conn:
        conn.execute(
            """
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, memory_domain,
                session_id, turn_id, content, author_type, content_type
            ) VALUES (
                'evt-chat-linked', 1700000100, 1700000100, 'UserMessage', 'chat', 1,
                'sess-vault-1', 'turn-vault-1', 'Remember our trip to Kyoto', 1, 1
            )
            """
        )
        conn.commit()
    with sqlite3.connect(paths.memory_db_path) as conn:
        conn.execute(
            """
            INSERT INTO manual_entries(entry_id, created_at, event_at, body, attachments_json)
            VALUES ('entry-vault-1', 1700000200, 1700000200, 'Kyoto note', ?)
            """,
            (json.dumps([f"manual-entry-asset://{manual_digest}.png"]),),
        )
        conn.commit()

    # 5. Seed chat.db
    with sqlite3.connect(paths.chat_db_path) as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, title_overridden, summary,
                created_at_ms, updated_at_ms, last_message_preview, last_user_message_preview, message_count
            ) VALUES (
                'sess-vault-1', 'local_user', 'Kyoto planning', 1, '',
                1700000000000, 1700000100000, 'Remember our trip to Kyoto', 'Remember our trip to Kyoto', 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, turn_id, user_id, role, message_kind,
                content_text, payload_json, is_final, is_visible, created_at_ms, sequence_no
            ) VALUES (
                'msg-vault-1', 'sess-vault-1', 'turn-vault-1', 'local_user', 'user', 'user_text',
                'Remember our trip to Kyoto', '{}', 1, 1, 1700000100000, 1
            )
            """
        )
        conn.commit()

    # 6. Seed persona_registry.db
    with sqlite3.connect(paths.persona_registry_db_path) as conn:
        conn.execute(
            """
            INSERT INTO personas(
                persona_id, name, slug, locale, config_json, is_builtin,
                seed_slug, group_name, sort_order, description, avatar_path, created_at, updated_at
            ) VALUES (
                'persona-custom-1', 'Aoi', 'aoi', 'en', '{"name":"Aoi"}', 0,
                NULL, 'custom', 1, 'Custom companion', 'custom_companion.png', 1700000000, 1700000000
            )
            """
        )
        conn.commit()

    # 7. Seed growth_memory.db
    with sqlite3.connect(paths.growth_db_path) as conn:
        conn.execute(
            """
            INSERT INTO milestones(
                id, type, title, description, timestamp, metadata, persona_id
            ) VALUES (
                'ms-1', 'first_conversation', 'First Kyoto chat', 'Discussed Kyoto',
                1700000100, '{}', 'persona-custom-1'
            )
            """
        )
        conn.commit()

    # 8. Seed emotional_state.db
    with sqlite3.connect(paths.emotional_db_path) as conn:
        conn.execute(
            """
            INSERT INTO emotional_state(key, value, updated_at)
            VALUES ('current_mood', '{"mood":"warm","energy":0.75}', 1700000100)
            """
        )
        conn.commit()

    # 9. Seed personal_tasks.db
    with sqlite3.connect(paths.personal_tasks_db_path) as conn:
        conn.execute(
            """
            INSERT INTO personal_items(
                id, user_id, kind, title, status, timezone, origin, version, created_at, updated_at
            ) VALUES (
                'task-kyoto-1', 'local_user', 'action', 'Book Kyoto rail pass', 'active',
                'UTC', 'user', 1, 1700000100, 1700000100
            )
            """
        )
        conn.commit()

    return {
        "manual_asset": manual_bytes,
        "manual_digest": manual_digest.encode("ascii"),
        "chat_img": chat_img_bytes,
        "avatar": avatar_bytes,
    }


@pytest.mark.asyncio
async def test_full_encrypted_vault_v2_backup_and_clean_home_restore_roundtrip(
    tmp_path: Path,
) -> None:
    src_paths = RuntimePaths(tmp_path / "source-home")
    src_archive = src_paths.memory_dir / "archive"
    src_archive.mkdir(parents=True, exist_ok=True)
    seeded = _seed_full_vault(src_paths)

    snapshot = await create_memory_snapshot(
        runtime_paths=src_paths,
        archive_dir=src_archive,
        unified_memory=None,
        include_l0=True,
    )
    try:
        backup_path, manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=tmp_path,
            encryption="password",
            password="vault-v2-strong-passphrase",
        )
    finally:
        discard_snapshot(snapshot)

    assert manifest.format_version == 2
    assert manifest.counts["l1_events"] == 1
    assert manifest.counts["chat_messages"] == 1
    assert manifest.counts["chat_attachments"] == 1
    assert manifest.counts["personas"] == 1
    assert manifest.counts["growth_milestones"] == 1
    assert manifest.counts["emotional_states"] == 1
    assert manifest.counts["personal_tasks"] == 1
    assert manifest.counts["user_avatars"] == 1
    assert manifest.counts["manual_entry_assets"] == 1
    assert "device_credentials_and_caches_not_included" in manifest.limitations

    # Restore into a brand-new, clean MAGI_HOME (with empty initialized L1/memory DBs).
    dst_paths = RuntimePaths(tmp_path / "clean-target-home")
    dst_archive = dst_paths.memory_dir / "archive"
    dst_archive.mkdir(parents=True, exist_ok=True)
    run_upgrade_head(
        dst_paths,
        targets=tuple(t for t in MIGRATION_TARGETS if t.name in {"l1", "memory_shared"}),
    )

    inspection = inspect_memory_backup(
        source_path=backup_path,
        password="vault-v2-strong-passphrase",
        runtime_paths=dst_paths,
        archive_target=dst_archive,
    )
    assert inspection.candidate_id is not None
    assert inspection.counts == manifest.counts

    candidate_root, metadata, loaded_manifest = load_restore_candidate(
        runtime_paths=dst_paths,
        candidate_id=inspection.candidate_id,
        fingerprint=inspection.fingerprint,
    )
    candidate = ValidatedRestoreCandidate.from_preflight(
        candidate_root=candidate_root,
        metadata=metadata,
        manifest=loaded_manifest,
    )
    tx = await prepare_memory_restore(
        candidate=candidate,
        runtime_paths=dst_paths,
    )
    tx.cutover()
    tx.commit()
    tx.finalize_commit()

    # Assert 100% lossless restoration across every personal vault domain.
    with sqlite3.connect(dst_paths.chat_db_path) as conn:
        assert conn.execute(
            "SELECT session_id, content_text FROM chat_messages WHERE message_id = 'msg-vault-1'"
        ).fetchone() == ("sess-vault-1", "Remember our trip to Kyoto")
    with sqlite3.connect(dst_paths.l1_memory_db_path) as conn:
        assert conn.execute(
            "SELECT session_id, turn_id FROM fact_events WHERE event_id = 'evt-chat-linked'"
        ).fetchone() == ("sess-vault-1", "turn-vault-1")
    with sqlite3.connect(dst_paths.persona_registry_db_path) as conn:
        assert conn.execute(
            "SELECT name, avatar_path FROM personas WHERE persona_id = 'persona-custom-1'"
        ).fetchone() == ("Aoi", "custom_companion.png")
    with sqlite3.connect(dst_paths.growth_db_path) as conn:
        assert conn.execute(
            "SELECT title FROM milestones WHERE id = 'ms-1'"
        ).fetchone() == ("First Kyoto chat",)
    with sqlite3.connect(dst_paths.emotional_db_path) as conn:
        assert conn.execute(
            "SELECT value FROM emotional_state WHERE key = 'current_mood'"
        ).fetchone() == ('{"mood":"warm","energy":0.75}',)
    with sqlite3.connect(dst_paths.personal_tasks_db_path) as conn:
        assert conn.execute(
            "SELECT title, status FROM personal_items WHERE id = 'task-kyoto-1'"
        ).fetchone() == ("Book Kyoto rail pass", "active")

    assert (dst_paths.chat_resources_dir / "images" / "session-1" / "photo.png").read_bytes() == seeded["chat_img"]
    assert (vault_user_avatar_dir(dst_paths) / "custom_companion.png").read_bytes() == seeded["avatar"]
    digest = seeded["manual_digest"].decode("ascii")
    assert (dst_paths.manual_entry_assets_dir / digest[:2] / f"{digest}.png").read_bytes() == seeded["manual_asset"]


@pytest.mark.asyncio
async def test_preflight_accepts_zip64_and_vault_cutover_failure_rolls_back(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "zip64-home")
    archive_dir = paths.memory_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    _seed_full_vault(paths)

    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=archive_dir,
        unified_memory=None,
        include_l0=True,
    )
    try:
        backup_path, manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=tmp_path,
            encryption="none",
            password=None,
        )
    finally:
        discard_snapshot(snapshot)

    # Re-package the exact same members with force_zip64=True to verify ZIP64 parser acceptance.
    zip64_path = tmp_path / "forced-zip64.magibackup"
    with zipfile.ZipFile(backup_path, "r") as src_zip, zipfile.ZipFile(
        zip64_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as dst_zip:
        for info in src_zip.infolist():
            new_info = zipfile.ZipInfo(info.filename)
            new_info.compress_type = zipfile.ZIP_DEFLATED
            new_info.external_attr = 0o100600 << 16
            data = src_zip.read(info.filename)
            new_info.file_size = len(data)
            with dst_zip.open(new_info, "w", force_zip64=True) as handle:
                handle.write(data)

    inspection = inspect_memory_backup(
        source_path=zip64_path,
        password=None,
        runtime_paths=paths,
        archive_target=archive_dir,
    )
    assert inspection.candidate_id is not None
    assert inspection.counts == manifest.counts

    # Mutate live personal_tasks.db, then inject a failure after vault cutover and assert full rollback.
    with sqlite3.connect(paths.personal_tasks_db_path) as conn:
        conn.execute("UPDATE personal_items SET title = 'Live modified task' WHERE id = 'task-kyoto-1'")
        conn.commit()

    candidate_root, metadata, loaded_manifest = load_restore_candidate(
        runtime_paths=paths,
        candidate_id=inspection.candidate_id,
        fingerprint=inspection.fingerprint,
    )
    candidate = ValidatedRestoreCandidate.from_preflight(
        candidate_root=candidate_root,
        metadata=metadata,
        manifest=loaded_manifest,
    )

    def fail_after_vault(stage: str) -> None:
        if stage == "after_vault_cutover":
            raise RuntimeError("injected vault failure")

    tx = await prepare_memory_restore(
        candidate=candidate,
        runtime_paths=paths,
        failpoint=fail_after_vault,
    )
    with pytest.raises(RuntimeError, match="injected vault failure"):
        tx.cutover()

    with sqlite3.connect(paths.personal_tasks_db_path) as conn:
        assert conn.execute(
            "SELECT title FROM personal_items WHERE id = 'task-kyoto-1'"
        ).fetchone() == ("Live modified task",)


def test_argon2_parameter_range_accepts_stronger_profile_and_rejects_weak(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    plaintext = tmp_path / "plain.zip"
    plaintext.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    def _pack_with_params(out_path: Path, memory_kib: int, iterations: int, lanes: int) -> None:
        salt = b"0123456789abcdef"
        nonce = b"0123456789ab"
        header = _HEADER.pack(
            ENCRYPTED_BACKUP_MAGIC,
            salt,
            nonce,
            memory_kib,
            iterations,
            lanes,
        )
        key = _derive_key("secret-pass", salt, memory_kib, iterations, lanes)
        enc = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        enc.authenticate_additional_data(header)
        ct = enc.update(plaintext.read_bytes()) + enc.finalize()
        out_path.write_bytes(header + ct + enc.tag)

    stronger = tmp_path / "stronger.magibackup"
    _pack_with_params(stronger, 96 * 1024, 4, 2)
    decrypted = tmp_path / "decrypted.zip"
    decrypt_backup_payload(stronger, decrypted, "secret-pass")
    assert decrypted.read_bytes() == plaintext.read_bytes()

    weak = tmp_path / "weak.magibackup"
    _pack_with_params(weak, 4 * 1024, 1, 1)
    with pytest.raises(MemoryPortabilityError) as err:
        decrypt_backup_payload(weak, tmp_path / "weak-out.zip", "secret-pass")
    assert err.value.code == "encryption_parameters_invalid"
