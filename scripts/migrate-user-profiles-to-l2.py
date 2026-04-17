#!/usr/bin/env python3
"""Migrate legacy UserProfileMemory Markdown profiles into L2 cognition stores.

Reads ``~/.magi/others/*.md`` profiles and:
  1. Upserts each user as an L2 entity with ``canonical_name``.
  2. Upserts user preferences as ToM ``preference_profile`` assertions.
  3. Refreshes the ToM snapshot so that ``UserProfileService`` can read them.

Safe to run multiple times — all L2 writes are idempotent.

Usage:
    python scripts/migrate-user-profiles-to-l2.py [--base-dir ~/.magi] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_SRC_DIR = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC_DIR))

from magi.memory.l2.entity_catalog import L2EntityCatalog  # noqa: E402
from magi.memory.l2.store import L2CognitionStore  # noqa: E402
from magi.utils.runtime import get_runtime_paths, set_runtime_dir  # noqa: E402


# ---------------------------------------------------------------------------
# Markdown parsing (ported from the retired UserProfileMemory formatter)
# ---------------------------------------------------------------------------

def _parse_profile_md(content: str, user_id: str) -> Dict[str, Any]:
    """Parse a legacy profile Markdown file into a flat dict."""
    data: Dict[str, Any] = {
        "user_id": user_id,
        "name": user_id,
        "nickname": "",
        "interests": [],
        "habits": [],
        "personality_traits": [],
        "communication_style": "",
        "preferences": {},
    }

    name_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    if name_match:
        data["name"] = name_match.group(1).strip()

    nickname_match = re.search(r"Nickname: ([^\n]+)", content)
    if nickname_match:
        data["nickname"] = nickname_match.group(1).strip()

    style_match = re.search(r"\*\*Communication style\*\*: ([^\n]+)", content)
    if style_match:
        data["communication_style"] = style_match.group(1).strip()

    current_section = None
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith(">"):
            continue

        if line.startswith("## "):
            section = line[3:].strip().lower()
            if "interest" in section:
                current_section = "interests"
            elif "habit" in section:
                current_section = "habits"
            elif "character" in section or "trait" in section:
                current_section = "personality"
            elif "preference" in section:
                current_section = "preferences"
            else:
                current_section = None
        elif line.startswith("- ") and current_section:
            item = line[2:].strip()
            if item.startswith("*") and item.endswith("*"):
                continue  # skip "No records yet" placeholders
            if current_section == "interests":
                data["interests"].append(item)
            elif current_section == "habits":
                data["habits"].append(item)
            elif current_section == "personality":
                data["personality_traits"].append(item)
            elif current_section == "preferences":
                kv = re.match(r"\*\*(.+?)\*\*:\s*(.+)", item)
                if kv:
                    data["preferences"][kv.group(1).strip()] = kv.group(2).strip()

    return data


def _build_assertions(
    profile: Dict[str, Any],
    entity_id: str,
) -> List[Dict[str, Any]]:
    """Convert parsed profile fields into L2 ToM assertion candidates."""
    now = time.time()
    assertions: List[Dict[str, Any]] = []

    base = {
        "entity_id": entity_id,
        "entity_type": "user",
        "confidence_score": 0.85,
        "validation_state": "stable",
        "temporal_scope": "persistent",
        "source_domain": "migration",
        "inference_depth": "explicit_fact",
        "evidence_events": [],
        "first_inferred_at": now,
        "last_validated_at": now,
        "volatility_index": 0.15,
    }

    # preferences dict → preference_profile assertions
    for key, value in profile.get("preferences", {}).items():
        assertions.append({
            **base,
            "trait_family": "preference_profile",
            "trait_name": f"preference.{key}",
            "trait_value": str(value),
        })

    # interests → taste_profile assertions
    for interest in profile.get("interests", []):
        assertions.append({
            **base,
            "trait_family": "taste_profile",
            "trait_name": f"interest.{interest.lower().replace(' ', '_')}",
            "trait_value": interest,
        })

    # communication style
    style = profile.get("communication_style", "").strip()
    if style and style != "friendly":
        assertions.append({
            **base,
            "trait_family": "preference_profile",
            "trait_name": "preference.communication_style",
            "trait_value": style,
        })

    return assertions


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

async def _migrate_one(
    profile: Dict[str, Any],
    catalog: L2EntityCatalog,
    store: L2CognitionStore,
    dry_run: bool,
) -> Tuple[str, int]:
    """Migrate a single profile. Returns (entity_id, assertion_count)."""
    user_id = profile["user_id"]
    name = profile.get("name") or user_id
    entity_id = f"user:{user_id}"

    if dry_run:
        assertions = _build_assertions(profile, entity_id)
        return entity_id, len(assertions)

    # 1. Upsert entity
    entity_id = await catalog.upsert_entity(
        canonical_name=name,
        entity_type="user",
        entity_id=entity_id,
    )

    # 2. Add nickname as alias
    nickname = profile.get("nickname", "").strip()
    if nickname and nickname.lower() != "none":
        await catalog.add_alias(entity_id=entity_id, alias_text=nickname)

    # 3. Upsert assertions
    assertions = _build_assertions(profile, entity_id)
    for assertion in assertions:
        await store.upsert_assertion_candidate(assertion)

    # 4. Refresh snapshot
    await store.refresh_entity_snapshot(entity_id=entity_id, entity_type="user")

    return entity_id, len(assertions)


async def _run(args: argparse.Namespace) -> None:
    if args.base_dir:
        set_runtime_dir(args.base_dir)

    runtime_paths = get_runtime_paths()
    others_dir = runtime_paths.others_dir

    if not others_dir.exists():
        print(f"No legacy profiles directory found at {others_dir}")
        return

    md_files = sorted(others_dir.glob("*.md"))
    if not md_files:
        print(f"No Markdown profile files in {others_dir}")
        return

    print(f"Found {len(md_files)} legacy profile(s) in {others_dir}")

    if args.dry_run:
        print("[DRY RUN] — no writes will be performed\n")

    # Parse all profiles first
    profiles: List[Dict[str, Any]] = []
    for md_file in md_files:
        user_id = md_file.stem
        try:
            content = md_file.read_text(encoding="utf-8")
            profile = _parse_profile_md(content, user_id)
            profiles.append(profile)
        except Exception as exc:
            print(f"  SKIP {md_file.name}: parse error — {exc}")

    if not profiles:
        print("No valid profiles to migrate.")
        return

    # Initialize L2 stores
    catalog: L2EntityCatalog | None = None
    store: L2CognitionStore | None = None

    if not args.dry_run:
        db_path = runtime_paths.memory_db_path
        catalog = L2EntityCatalog(db_path=str(db_path))
        await catalog.initialize()
        store = L2CognitionStore(db_path=str(db_path))
        await store.initialize()

    total_assertions = 0
    for profile in profiles:
        entity_id, n_assertions = await _migrate_one(
            profile, catalog, store, dry_run=args.dry_run,
        )
        total_assertions += n_assertions
        tag = "[DRY RUN] " if args.dry_run else ""
        print(f"  {tag}{profile['name']} ({profile['user_id']}) → {entity_id}  [{n_assertions} assertions]")

    print(f"\nMigrated {len(profiles)} profile(s), {total_assertions} assertion(s) total.")
    if not args.dry_run:
        print("Legacy profile files are preserved — delete them manually after verifying.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy Markdown user profiles into L2 cognition stores.",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Magi runtime home override (defaults to ~/.magi).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print what would be migrated, without writing.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
