"""Present conflict notifications from the L2 domain's retained assertion pairs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from magi.i18n import effective_app_language_code

from ..assertion_display import SummaryPolicy, decorate_assertion_display, render_assertion_display
from ..retrieval.shadow_conflicts import ShadowConflictPair, ShadowConflictReader, ShadowConflictRef


def profile_conflict_title(*, language: str | None = None) -> str:
    """Return a title that does not expose an internal trait slot."""
    language = language or effective_app_language_code()
    return "有两条记忆需要核对" if language.startswith("zh") else "Two memory records need review"


async def render_profile_conflict_notifications(
    *,
    db_path: str | None,
    pairs: Sequence[ShadowConflictPair],
    language: str | None = None,
) -> list[tuple[str, str]]:
    """Describe domain-selected pairs without extending source-text visibility."""
    language = language or effective_app_language_code()
    assertions = [side or {} for pair in pairs for side in (pair.authoritative, pair.shadow)]
    projected = await decorate_assertion_display(
        db_path,
        assertions,
        summary_policy=SummaryPolicy.STRUCTURED_ONLY,
    )
    result = []
    for index in range(0, len(projected), 2):
        previous, candidate = [
            render_assertion_display(
                item,
                language=language,
                summary_policy=SummaryPolicy.STRUCTURED_ONLY,
            )
            for item in projected[index : index + 2]
        ]
        body = (
            f"已有记录：{previous}\n待确认候选：{candidate}"
            if language.startswith("zh")
            else f"Existing record: {previous}\nCandidate awaiting confirmation: {candidate}"
        )
        result.append((profile_conflict_title(language=language), body))
    return result


async def project_profile_conflict_notifications(
    store: ShadowConflictReader | None,
    payloads: Sequence[Mapping[str, Any]],
) -> list[tuple[str, str]]:
    """Resolve stored references through the domain before formatting their facts."""
    references = [
        ShadowConflictRef(
            shadow_id=value if isinstance(value := payload.get("shadow_id"), str) else None,
            authoritative_id=(
                value if isinstance(value := payload.get("authoritative_id"), str) else None
            ),
        )
        for payload in payloads
    ]
    pairs = (
        await store.get_shadow_conflict_pairs(references=references)
        if store is not None
        else [ShadowConflictPair() for _ in references]
    )
    return await render_profile_conflict_notifications(
        db_path=store.db_path if store is not None else None,
        pairs=pairs,
    )
