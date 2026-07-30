#!/usr/bin/env python3
"""Validate gateway-visible API route ownership metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ROUTING_FUNCTION_RE = re.compile(r"axum::routing::(get|post|put|patch|delete)\s*\(")
CHAINED_METHOD_RE = re.compile(r"\.(get|post|put|patch|delete)\s*\(")
STRING_ARG_RE = re.compile(r'^\s*"([^"]+)"\s*,', re.S)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_keys = {"access_policy", "native_routes", "static_mounts", "proxied_prefixes"}
    missing = sorted(required_keys - set(manifest))
    if missing:
        raise ValueError(f"Manifest missing required keys: {', '.join(missing)}")

    for collection_name in ("native_routes", "static_mounts", "proxied_prefixes"):
        if not isinstance(manifest[collection_name], list):
            raise ValueError(f"Manifest key {collection_name!r} must be a list")

    for source_key in ("router_source", "python_app_source"):
        source_path = root / manifest[source_key]
        if not source_path.exists():
            raise ValueError(f"Manifest {source_key} does not exist: {manifest[source_key]}")

    return manifest


def find_matching_paren(source: str, open_index: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_index, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("Could not find matching closing parenthesis")


def iter_method_call_arguments(source: str, method_name: str) -> list[str]:
    marker = f".{method_name}("
    arguments: list[str] = []
    search_from = 0
    while True:
        marker_index = source.find(marker, search_from)
        if marker_index < 0:
            return arguments
        open_index = marker_index + len(marker) - 1
        close_index = find_matching_paren(source, open_index)
        arguments.append(source[open_index + 1 : close_index])
        search_from = close_index + 1


def parse_rust_routes(root: Path, router_source: str) -> dict[str, set[str]]:
    source = (root / router_source).read_text(encoding="utf-8")
    routes: dict[str, set[str]] = {}
    for arguments in iter_method_call_arguments(source, "route"):
        match = STRING_ARG_RE.search(arguments)
        if not match:
            raise ValueError(f"Could not parse route path from .route({arguments[:80]!r}...)")
        path = match.group(1)
        methods = {method.upper() for method in ROUTING_FUNCTION_RE.findall(arguments)}
        methods.update(method.upper() for method in CHAINED_METHOD_RE.findall(arguments))
        if not methods:
            raise ValueError(f"Could not parse HTTP methods for Rust route {path}")
        routes.setdefault(path, set()).update(methods)
    return routes


def parse_rust_static_mounts(root: Path, router_source: str) -> set[str]:
    source = (root / router_source).read_text(encoding="utf-8")
    mounts: set[str] = set()
    for arguments in iter_method_call_arguments(source, "nest_service"):
        match = STRING_ARG_RE.search(arguments)
        if not match:
            raise ValueError(f"Could not parse path from .nest_service({arguments[:80]!r}...)")
        mounts.add(match.group(1))
    return mounts


def parse_python_routes(root: Path) -> dict[str, set[str]]:
    backend_src = root / "backend" / "src"
    sys.path.insert(0, str(backend_src))

    from fastapi.routing import APIRoute  # type: ignore[import-not-found]
    from magi.utils.runtime import set_runtime_dir

    def iter_leaf_routes(router, prefix=""):
        """Yield (full_path, methods) for every leaf APIRoute, descending into
        included sub-routers.

        fastapi <0.137 flattens ``include_router`` into ``APIRoute`` objects with
        the prefix already baked into ``route.path``. fastapi >=0.137 instead
        appends one ``_IncludedRouter`` wrapper per ``include_router`` call,
        exposing the child via ``include_context.included_router`` and the
        include-time prefix via ``include_context.prefix``. Descend through both
        shapes (compounding prefixes) so route discovery is version-agnostic and
        reproduces the historical flattened path set.
        """
        for route in getattr(router, "routes", ()):
            if isinstance(route, APIRoute):
                methods = {m for m in (route.methods or set()) if m in HTTP_METHODS}
                if methods:
                    yield prefix + route.path, methods
                continue
            ctx = getattr(route, "include_context", None)
            child = getattr(ctx, "included_router", None) if ctx is not None else None
            if child is None:
                child = getattr(route, "original_router", None)
            if child is None and hasattr(route, "routes"):
                child = route
            if child is not None and child is not router:
                child_prefix = prefix + ((getattr(ctx, "prefix", "") or "") if ctx is not None else "")
                yield from iter_leaf_routes(child, child_prefix)

    with tempfile.TemporaryDirectory(prefix="magi-api-contract-") as runtime_dir:
        set_runtime_dir(Path(runtime_dir))
        from magi.transport.http_app import create_transport_app

        app = create_transport_app()
        routes: dict[str, set[str]] = {}
        for path, methods in iter_leaf_routes(app):
            routes.setdefault(path, set()).update(methods)
        return routes


def normalize_methods(methods: Any, *, context: str) -> set[str]:
    if not isinstance(methods, list) or not methods:
        raise ValueError(f"{context} must define a non-empty methods list")
    normalized = {str(method).upper() for method in methods}
    unknown = sorted(normalized - HTTP_METHODS)
    if unknown:
        raise ValueError(f"{context} has unsupported methods: {', '.join(unknown)}")
    return normalized


def validate_manifest_shape(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen_routes: set[str] = set()
    for route in manifest["native_routes"]:
        path = route.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append(f"Native route has invalid path: {path!r}")
            continue
        if path in seen_routes:
            errors.append(f"Duplicate native route path in manifest: {path}")
        seen_routes.add(path)
        try:
            normalize_methods(route.get("methods"), context=f"Native route {path}")
        except ValueError as exc:
            errors.append(str(exc))
        owner_file = route.get("owner_file")
        if not isinstance(owner_file, str) or not (root / owner_file).exists():
            errors.append(f"Native route {path} owner_file does not exist: {owner_file!r}")
        parity = route.get("python_parity")
        if parity is not None:
            parity_file = parity.get("owner_file") if isinstance(parity, dict) else None
            if not isinstance(parity_file, str) or not (root / parity_file).exists():
                errors.append(f"Native route {path} python_parity owner_file does not exist: {parity_file!r}")

    for mount in manifest["static_mounts"]:
        path = mount.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append(f"Static mount has invalid path: {path!r}")
        owner_file = mount.get("owner_file")
        if not isinstance(owner_file, str) or not (root / owner_file).exists():
            errors.append(f"Static mount {path} owner_file does not exist: {owner_file!r}")

    for prefix in manifest["proxied_prefixes"]:
        value = prefix.get("prefix")
        if not isinstance(value, str) or not value.startswith("/"):
            errors.append(f"Proxied prefix has invalid value: {value!r}")
        owner_file = prefix.get("owner_file")
        if not isinstance(owner_file, str) or not (root / owner_file).exists():
            errors.append(f"Proxied prefix {value} owner_file does not exist: {owner_file!r}")

    errors.extend(validate_access_policy(manifest))
    return errors


def string_set(value: Any, *, context: str) -> tuple[set[str], list[str]]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return set(), [f"{context} must be a list of strings"]
    if len(value) != len(set(value)):
        return set(value), [f"{context} must not contain duplicates"]
    return set(value), []


def validate_access_policy(manifest: dict[str, Any]) -> list[str]:
    policy = manifest.get("access_policy")
    if not isinstance(policy, dict):
        return ["Manifest access_policy must be an object"]

    errors: list[str] = []
    if policy.get("default") != "desktop-session":
        errors.append("Access policy default must be desktop-session")

    expected_keys = {
        "default",
        "public_native_routes",
        "public_static_mounts",
        "ticket_native_routes",
        "ticket_proxied_prefixes",
        "ticket_static_mounts",
    }
    unknown_keys = sorted(set(policy) - expected_keys)
    missing_keys = sorted(expected_keys - set(policy))
    if unknown_keys:
        errors.append(f"Access policy has unknown keys: {', '.join(unknown_keys)}")
    if missing_keys:
        errors.append(f"Access policy is missing keys: {', '.join(missing_keys)}")

    parsed: dict[str, set[str]] = {}
    for key in expected_keys - {"default"}:
        values, value_errors = string_set(policy.get(key), context=f"Access policy {key}")
        parsed[key] = values
        errors.extend(value_errors)

    native_paths = {
        route.get("path")
        for route in manifest["native_routes"]
        if isinstance(route.get("path"), str)
    }
    static_mounts = {
        mount.get("path")
        for mount in manifest["static_mounts"]
        if isinstance(mount.get("path"), str)
    }
    proxied_prefixes = {
        prefix.get("prefix")
        for prefix in manifest["proxied_prefixes"]
        if isinstance(prefix.get("prefix"), str)
    }

    for key in ("public_native_routes", "ticket_native_routes"):
        for path in sorted(parsed.get(key, set()) - native_paths):
            errors.append(f"Access policy {key} references unknown native route: {path}")

    public_mounts = parsed.get("public_static_mounts", set())
    ticket_mounts = parsed.get("ticket_static_mounts", set())
    for path in sorted((public_mounts | ticket_mounts) - static_mounts):
        errors.append(f"Access policy references unknown static mount: {path}")
    for path in sorted(static_mounts - public_mounts - ticket_mounts):
        errors.append(f"Static mount is missing an access classification: {path}")
    for path in sorted(public_mounts & ticket_mounts):
        errors.append(f"Static mount has conflicting access classifications: {path}")

    for prefix in sorted(parsed.get("ticket_proxied_prefixes", set())):
        if not any(path_matches_prefix(prefix, candidate) for candidate in proxied_prefixes):
            errors.append(
                f"Ticket resource prefix is not covered by a proxied prefix: {prefix}"
            )

    public_routes = parsed.get("public_native_routes", set())
    ticket_routes = parsed.get("ticket_native_routes", set())
    for path in sorted(public_routes & ticket_routes):
        errors.append(f"Native route has conflicting access classifications: {path}")
    if public_routes != {"/api/health"}:
        errors.append("Only /api/health may be a public native route")

    return errors


def path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def validate_contract(root: Path, manifest_path: Path) -> tuple[list[str], dict[str, Any]]:
    manifest = load_manifest(root, manifest_path)
    errors = validate_manifest_shape(root, manifest)

    rust_routes = parse_rust_routes(root, manifest["router_source"])
    rust_static_mounts = parse_rust_static_mounts(root, manifest["router_source"])
    python_routes = parse_python_routes(root)

    manifest_native_routes = {
        route["path"]: normalize_methods(route["methods"], context=f"Native route {route['path']}")
        for route in manifest["native_routes"]
        if isinstance(route.get("path"), str)
    }
    manifest_static_mounts = {mount["path"] for mount in manifest["static_mounts"] if isinstance(mount.get("path"), str)}
    proxied_prefixes = [prefix["prefix"] for prefix in manifest["proxied_prefixes"] if isinstance(prefix.get("prefix"), str)]
    ignored_python_routes = set(manifest.get("ignored_python_routes", []))

    for path, methods in sorted(rust_routes.items()):
        expected = manifest_native_routes.get(path)
        if expected is None:
            errors.append(f"Rust route missing from manifest: {path} {sorted(methods)}")
        elif expected != methods:
            errors.append(
                f"Rust route method mismatch for {path}: manifest={sorted(expected)} router={sorted(methods)}"
            )

    for path, methods in sorted(manifest_native_routes.items()):
        registered = rust_routes.get(path)
        if registered is None:
            errors.append(f"Manifest native route not registered in Rust gateway: {path} {sorted(methods)}")

    missing_mounts = sorted(rust_static_mounts - manifest_static_mounts)
    extra_mounts = sorted(manifest_static_mounts - rust_static_mounts)
    for path in missing_mounts:
        errors.append(f"Rust static mount missing from manifest: {path}")
    for path in extra_mounts:
        errors.append(f"Manifest static mount not registered in Rust gateway: {path}")

    native_parity = {
        (route["path"], method)
        for route in manifest["native_routes"]
        if route.get("python_parity") is not None
        for method in normalize_methods(route["methods"], context=f"Native route {route['path']}")
    }
    native_keys = {(path, method) for path, methods in rust_routes.items() for method in methods}

    for path, methods in sorted(python_routes.items()):
        if path in ignored_python_routes:
            continue
        for method in sorted(methods):
            key = (path, method)
            if key in native_keys:
                if key not in native_parity:
                    errors.append(f"Python route {method} {path} is shadowed by Rust but lacks python_parity metadata")
                continue
            if not any(path_matches_prefix(path, prefix) for prefix in proxied_prefixes):
                errors.append(f"Python route {method} {path} is not covered by a proxied prefix")

    for path, methods in sorted(manifest_native_routes.items()):
        route = next(route for route in manifest["native_routes"] if route["path"] == path)
        if route.get("python_parity") is None:
            continue
        python_methods = python_routes.get(path)
        if python_methods is None:
            errors.append(f"Native route {path} declares python_parity but Python app does not expose the path")
            continue
        missing_methods = sorted(methods - python_methods)
        if missing_methods:
            errors.append(
                f"Native route {path} declares python_parity for methods not exposed by Python: {missing_methods}"
            )

    inventory = {
        "rust_native_routes": {path: sorted(methods) for path, methods in sorted(rust_routes.items())},
        "rust_static_mounts": sorted(rust_static_mounts),
        "python_routes": {path: sorted(methods) for path, methods in sorted(python_routes.items())},
    }
    return errors, inventory


def main() -> int:
    root = repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "contracts" / "api" / "gateway_routes.json",
        help="Path to the gateway route manifest.",
    )
    parser.add_argument(
        "--print-inventory",
        action="store_true",
        help="Print the discovered Rust/Python route inventory as JSON.",
    )
    args = parser.parse_args()

    errors, inventory = validate_contract(root, args.manifest)
    if args.print_inventory:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    if errors:
        print("Gateway API contract check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Gateway API contract check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
