#!/usr/bin/env python3
"""Export the Python IPC FastAPI OpenAPI schema."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_openapi_schema(root: Path) -> dict[str, Any]:
    backend_src = root / "backend" / "src"
    backend_src_text = str(backend_src)
    if backend_src_text not in sys.path:
        sys.path.insert(0, backend_src_text)

    with contextlib.redirect_stdout(sys.stderr):
        from magi.transport.http_app import create_transport_app

        app = create_transport_app()
        schema = app.openapi()
    if not isinstance(schema, dict):
        raise RuntimeError("FastAPI did not return an OpenAPI object")
    return schema


def validate_schema(schema: dict[str, Any]) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise RuntimeError("OpenAPI schema does not contain paths")
    required_python_routes = {
        "/api/config/",
        "/api/messages/send",
        "/api/personas/active",
    }
    missing = sorted(required_python_routes - set(paths))
    if missing:
        raise RuntimeError(f"OpenAPI schema missing required Python routes: {', '.join(missing)}")
    rust_native_only_routes = {
        "/api/metrics/runtime/overview",
        "/api/tasks",
        "/api/schedules",
    }
    leaked = sorted(rust_native_only_routes & set(paths))
    if leaked:
        raise RuntimeError(f"OpenAPI schema includes Rust-native-only routes: {', '.join(leaked)}")


def main() -> int:
    root = repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the schema to this file instead of stdout.",
    )
    args = parser.parse_args()

    schema = build_openapi_schema(root)
    validate_schema(schema)
    content = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())