"""Minimal TOML serializer for MCPServerConfig round-trip.

Supports exactly what our config schema needs: scalars (str/bool/int/float),
flat string-keyed tables, string-list arrays, and string-keyed string-value
sub-tables (e.g. transport.env, transport.headers, tool_overrides.<name>).
We deliberately avoid pulling in `tomli_w` — the dialect is small.
"""

from __future__ import annotations

from typing import Any


def _escape_string(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return f'"{"".join(out)}"'


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _escape_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_scalar(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML scalar: {type(value).__name__}")


def _is_table(value: Any) -> bool:
    return isinstance(value, dict)


def dumps(data: dict[str, Any]) -> str:
    """Serialize a nested dict to TOML.

    Tables are emitted depth-first with bracketed headers; scalars / arrays
    inside the current table are emitted before its sub-tables.
    """
    lines: list[str] = []

    def emit(prefix: list[str], obj: dict[str, Any]) -> None:
        scalars: list[tuple[str, Any]] = []
        tables: list[tuple[str, dict[str, Any]]] = []
        for key, value in obj.items():
            if _is_table(value):
                tables.append((key, value))
            else:
                scalars.append((key, value))
        if prefix:
            lines.append("[" + ".".join(prefix) + "]")
        for key, value in scalars:
            lines.append(f"{key} = {_scalar(value)}")
        if scalars and tables:
            lines.append("")
        for i, (key, sub) in enumerate(tables):
            if i > 0 or scalars:
                if lines and lines[-1] != "":
                    lines.append("")
            emit(prefix + [key], sub)

    emit([], data)
    return "\n".join(lines).rstrip() + "\n"
