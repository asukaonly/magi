from __future__ import annotations
import os
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .config import MCPServerConfig
from .log_security import register_mcp_transport_secrets

_ENV_RE = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: str) -> str:
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _expand_strings(obj):
    if isinstance(obj, str):
        return _expand(obj)
    if isinstance(obj, dict):
        return {k: _expand_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_strings(v) for v in obj]
    return obj


class MCPConfigLoader:
    def __init__(self, root: Path):
        self.root = Path(root)

    def load_all(self) -> list[MCPServerConfig]:
        if not self.root.exists():
            return []
        out: list[MCPServerConfig] = []
        for path in sorted(self.root.glob("*.toml")):
            if path.name == "index.toml":
                continue
            try:
                with path.open("rb") as f:
                    data = tomllib.load(f)
                data = _expand_strings(data)
                register_mcp_transport_secrets(data)
                cfg = MCPServerConfig.model_validate(data)
            except Exception as e:
                raise ValueError(f"{path}: failed to load MCP config: {e}") from e
            stem = path.stem
            if cfg.server.id != stem:
                raise ValueError(
                    f"{path}: server.id={cfg.server.id!r} does not match filename {stem!r}"
                )
            out.append(cfg)
        return out
