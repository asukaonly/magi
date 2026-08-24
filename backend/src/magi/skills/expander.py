"""Render a user-invocable skill into a chat message body.

Mirrors Claude Code's `/skill-name` UX: the user types `/skill-name args`,
the backend expands the SKILL.md template with arguments, and the
expansion is sent as the user's next chat turn. Unlike tool commands —
which run synchronously and write a (command_invocation, command_result)
pair — skill expansion does *not* execute anything; it returns the
rendered prompt and lets the existing chat send pipeline carry it through
to the LLM.

Variable substitution mirrors ``SkillRunner._substitute_variables`` but
without dragging in the LLM-runner dependency tree:

- ``$@`` / ``$argumentS`` — all arguments joined by spaces
- ``$0`` / ``$1`` / ... — individual positional arguments
- ``$#`` — argument count
- ``${HOME}`` / ``${PWD}`` — env-derived
- ``${user_id}`` / ``${CLAUDE_session_id}`` — context-derived
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from .loader import SkillLoader
from .provider import resolve_skill_loader


@dataclass(slots=True)
class SkillExpansion:
    name: str
    rendered_prompt: str
    invocation_text: str
    description: str
    argument_hint: str | None
    allowed_tools: list[str] | None
    context_mode: str | None  # "fork" | None
    user_invocable: bool
    content_hash: str


def expand_skill(
    *,
    skill_name: str,
    arguments: list[str] | None = None,
    user_id: str = "",
    session_id: str = "",
    workspace: str | None = None,
    loader: SkillLoader | None = None,
) -> SkillExpansion | None:
    """Return a rendered SkillExpansion or None if the skill isn't found."""
    args = list(arguments or [])
    skill_loader = loader or resolve_skill_loader()
    skill = skill_loader.load_skill(skill_name)
    if skill is None:
        return None
    rendered = _substitute(
        skill.prompt_template,
        args,
        user_id=user_id,
        session_id=session_id,
        workspace=workspace or "",
    )
    invocation = f"/{skill_name}" + (f" {' '.join(args)}" if args else "")
    return SkillExpansion(
        name=skill_name,
        rendered_prompt=rendered,
        invocation_text=invocation,
        description=skill.frontmatter.description or "",
        argument_hint=skill.frontmatter.argument_hint,
        allowed_tools=list(skill.frontmatter.allowed_tools or []) or None,
        context_mode=skill.frontmatter.context,
        user_invocable=skill.frontmatter.user_invocable,
        content_hash=hashlib.sha256(
            skill.prompt_template.encode("utf-8")
        ).hexdigest(),
    )


def _substitute(
    template: str,
    arguments: list[str],
    *,
    user_id: str,
    session_id: str,
    workspace: str,
) -> str:
    out = template
    joined = " ".join(arguments)
    out = out.replace("$argumentS", joined)
    out = out.replace("$@", joined)
    out = out.replace("$#", str(len(arguments)))
    for i, arg in enumerate(arguments):
        out = out.replace(f"${i}", arg)
    out = out.replace("${user_id}", user_id)
    out = out.replace("${CLAUDE_session_id}", session_id)
    out = out.replace("${HOME}", os.path.expanduser("~"))
    out = out.replace(
        "${PWD}",
        os.path.realpath(os.path.expandvars(os.path.expanduser(workspace))) if workspace else "",
    )
    return out
