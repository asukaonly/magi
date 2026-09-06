"""Owner-bound provider function names over the canonical registry index."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_SAFE_NAME = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")


class ToolRegistryModelNamesMixin:
    """Keep protocol-safe aliases separate from connection-qualified host IDs."""

    def exported_tool_name(self, name: str, *, skill: bool = False) -> str:
        """Return a stable safe name and bind its lookup to the current owner."""
        canonical = f"skill_{name}" if skill else self.resolve_tool_name(name)
        with self._registration_lock:
            owner = (
                self._skills.get(name) if skill else self._tool_registration_tokens.get(canonical)
            )
            if owner is None:
                raise KeyError(name)
            if _SAFE_NAME.fullmatch(canonical) and (not skill or canonical not in self._tools):
                return canonical
            owners = self.__dict__.setdefault("_model_name_owners", {})
            for alias, record in tuple(owners.items()):
                if record[0] == canonical and record[1] is owner and record[2] == skill:
                    return alias
            for index in range(1000):
                material = canonical if index == 0 else f"{canonical}\0{index}"
                alias = "magi_" + hashlib.sha256(material.encode()).hexdigest()[:59]
                if alias not in self._tools and alias not in self._tool_aliases:
                    self._tool_aliases[alias] = canonical
                    owners[alias] = (canonical, owner, skill)
                    return alias
            raise ValueError("No unoccupied model function name is available")

    def remove_model_names(self, canonical: str) -> None:
        """Remove exported names when their owning contribution is disposed."""
        owners = self.__dict__.get("_model_name_owners", {})
        for alias, (target, _, _) in tuple(owners.items()):
            if target == canonical:
                owners.pop(alias, None)
                if self._tool_aliases.get(alias) == target:
                    self._tool_aliases.pop(alias, None)

    def _model_name_is_current(self, alias: str) -> bool:
        record: tuple[str, Any, bool] | None = self.__dict__.get("_model_name_owners", {}).get(
            alias
        )
        if record is None:
            return True
        canonical, owner, skill = record
        current = (
            self._skills.get(canonical.removeprefix("skill_"))
            if skill
            else self._tool_registration_tokens.get(canonical)
        )
        if current is owner:
            return True
        self.remove_model_names(canonical)
        return False
