#!/usr/bin/env python3
"""Validate Rust gateway SQLite write ownership metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRODUCTION_SQL_RE = re.compile(
    r"\b(?:(INSERT)\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"(UPDATE)\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"(DELETE)\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"(CREATE)\s+INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)\s+ON\s+([A-Za-z_][A-Za-z0-9_]*))\b",
    re.IGNORECASE,
)
TEST_MODULE_RE = re.compile(r"\n\s*#\[cfg\(test\)\]")


@dataclass(frozen=True, order=True)
class SqlOperation:
    file: str
    operation: str
    table: str
    index: str | None = None

    @classmethod
    def from_contract_entry(cls, entry: dict[str, Any]) -> "SqlOperation":
        file = entry.get("file")
        operation = entry.get("operation")
        table = entry.get("table")
        if not isinstance(file, str) or not file:
            raise ValueError(f"SQLite ownership entry has invalid file: {file!r}")
        if not isinstance(operation, str) or not operation:
            raise ValueError(f"SQLite ownership entry has invalid operation: {operation!r}")
        if not isinstance(table, str) or not table:
            raise ValueError(f"SQLite ownership entry has invalid table: {table!r}")
        index = entry.get("index")
        if index is not None and not isinstance(index, str):
            raise ValueError(f"SQLite ownership entry has invalid index: {index!r}")
        return cls(file=file, operation=operation.lower(), table=table, index=index)

    def label(self) -> str:
        index_part = f" index={self.index}" if self.index else ""
        return f"{self.file}: {self.operation} table={self.table}{index_part}"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_contract(root: Path, contract_path: Path) -> set[SqlOperation]:
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    entries = payload.get("allowed_gateway_sql")
    if not isinstance(entries, list):
        raise ValueError("SQLite ownership contract must define allowed_gateway_sql as a list")

    allowed: set[SqlOperation] = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise ValueError(f"SQLite ownership entry must be an object: {raw_entry!r}")
        operation = SqlOperation.from_contract_entry(raw_entry)
        if not (root / operation.file).exists():
            raise ValueError(f"SQLite ownership entry file does not exist: {operation.file}")
        allowed.add(operation)
    return allowed


def production_source(source: str) -> str:
    match = TEST_MODULE_RE.search(source)
    source = source[: match.start()] if match else source
    source = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    return source.replace("\\\n", " ")


def discover_gateway_sql(root: Path) -> set[SqlOperation]:
    gateway_src = root / "crates" / "magi-gateway" / "src"
    operations: set[SqlOperation] = set()
    for path in sorted(gateway_src.rglob("*.rs")):
        relative_path = path.relative_to(root).as_posix()
        source = production_source(path.read_text(encoding="utf-8"))
        for match in PRODUCTION_SQL_RE.finditer(source):
            if match.group(1):
                operations.add(SqlOperation(relative_path, "insert", match.group(2)))
            elif match.group(3):
                table = match.group(4)
                if table.upper() != "SET":
                    operations.add(SqlOperation(relative_path, "update", table))
            elif match.group(5):
                operations.add(SqlOperation(relative_path, "delete", match.group(6)))
            elif match.group(7):
                operations.add(
                    SqlOperation(
                        relative_path,
                        "create_index",
                        match.group(9),
                        index=match.group(8),
                    )
                )
    return operations


def validate_ownership(root: Path, contract_path: Path) -> tuple[list[str], dict[str, Any]]:
    allowed = load_contract(root, contract_path)
    discovered = discover_gateway_sql(root)

    errors: list[str] = []
    for operation in sorted(discovered - allowed):
        errors.append(f"Rust gateway SQLite operation is not declared: {operation.label()}")
    for operation in sorted(allowed - discovered):
        errors.append(f"SQLite ownership contract entry is stale or unused: {operation.label()}")

    inventory = {
        "allowed": [operation.__dict__ for operation in sorted(allowed)],
        "discovered": [operation.__dict__ for operation in sorted(discovered)],
    }
    return errors, inventory


def main() -> int:
    root = repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=root / "contracts" / "sqlite" / "gateway_writes.json",
        help="Path to the SQLite gateway ownership contract.",
    )
    parser.add_argument(
        "--print-inventory",
        action="store_true",
        help="Print discovered and allowed gateway SQLite operations as JSON.",
    )
    args = parser.parse_args()

    errors, inventory = validate_ownership(root, args.contract)
    if args.print_inventory:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    if errors:
        print("SQLite ownership check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("SQLite ownership check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
