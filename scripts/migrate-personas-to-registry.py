#!/usr/bin/env python3
"""Import file-based persona JSON configs into the persona registry."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def configure_import_path(root: Path) -> None:
    backend_src = str(root / "backend" / "src")
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)


@dataclass(frozen=True, slots=True)
class PersonaMigrationReport:
    imported: int = 0
    skipped_existing: int = 0
    invalid: int = 0
    active_persona_id: str | None = None


async def import_persona_directory(
    *,
    source_dir: Path,
    db_path: Path,
    locale: str,
    set_active_slug: str | None = None,
    dry_run: bool = False,
) -> PersonaMigrationReport:
    from magi.personality.persona_repository import PersonaRepository

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Persona source directory does not exist: {source_dir}")

    repo = PersonaRepository(str(db_path))
    if not dry_run:
        await repo.init()

    imported = 0
    skipped_existing = 0
    invalid = 0
    imported_or_existing_by_slug: dict[str, str] = {}

    for persona_file in sorted(source_dir.glob("*.json")):
        slug = persona_file.stem
        try:
            raw = persona_file.read_text(encoding="utf-8")
            json.loads(raw)
        except Exception:
            invalid += 1
            continue

        existing = None
        if not dry_run:
            try:
                existing = await repo.get_by_slug(slug)
            except KeyError:
                existing = None

        if existing is not None:
            skipped_existing += 1
            imported_or_existing_by_slug[slug] = existing.persona_id
            continue

        imported += 1
        if dry_run:
            continue

        persona_id = await repo.create(config_json=raw, locale=locale, slug=slug)
        imported_or_existing_by_slug[slug] = persona_id

    active_persona_id = None
    if set_active_slug:
        if dry_run:
            active_persona_id = imported_or_existing_by_slug.get(set_active_slug)
        else:
            active_persona_id = imported_or_existing_by_slug.get(set_active_slug)
            if active_persona_id is None:
                try:
                    active_persona_id = (await repo.get_by_slug(set_active_slug)).persona_id
                except KeyError as exc:
                    raise KeyError(f"Cannot set active persona; slug not imported: {set_active_slug}") from exc
            await repo.set_active(active_persona_id)

    return PersonaMigrationReport(
        imported=imported,
        skipped_existing=skipped_existing,
        invalid=invalid,
        active_persona_id=active_persona_id,
    )


def _parse_args() -> argparse.Namespace:
    root = repository_root()
    configure_import_path(root)

    from magi.utils.runtime import get_runtime_paths

    runtime_paths = get_runtime_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=runtime_paths.personalities_dir,
        help="Directory containing legacy persona JSON files.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=runtime_paths.persona_registry_db_path,
        help="Persona registry SQLite database path.",
    )
    parser.add_argument("--locale", default="en", help="Locale to assign to imported personas.")
    parser.add_argument("--set-active-slug", help="Set this imported or existing slug as active.")
    parser.add_argument("--dry-run", action="store_true", help="Validate files and print counts without writing.")
    return parser.parse_args()


async def _amain() -> int:
    root = repository_root()
    configure_import_path(root)
    args = _parse_args()
    try:
        report = await import_persona_directory(
            source_dir=args.source_dir,
            db_path=args.db_path,
            locale=args.locale,
            set_active_slug=args.set_active_slug,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Persona migration failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Persona migration complete: "
        f"imported={report.imported}, "
        f"skipped_existing={report.skipped_existing}, "
        f"invalid={report.invalid}"
    )
    if report.active_persona_id:
        print(f"Active persona set to {report.active_persona_id}")
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())