"""Attach existing L2 experience relationships to timeline clusters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _ExperienceChapterReference:
    chapter_id: str
    title: str
    episode_ids: frozenset[str]
    event_ids: frozenset[str]


@dataclass(frozen=True)
class _ExperienceReference:
    experience_id: str
    title: str
    episode_ids: frozenset[str]
    event_ids: frozenset[str]
    chapters: tuple[_ExperienceChapterReference, ...]


@dataclass(frozen=True)
class _ExperienceMatch:
    reference: _ExperienceReference
    chapter: _ExperienceChapterReference | None
    score: tuple[int, int, int]


class TimelineExperienceLinker:
    """Decorate viewport clusters with existing active experience references."""

    def __init__(self, *, l2_store: Any | None) -> None:
        self._l2 = l2_store

    async def decorate(
        self,
        clusters: list[dict[str, Any]],
        *,
        start: float,
        end: float,
    ) -> list[dict[str, Any]]:
        """Return cluster copies decorated with truth-backed experience links."""
        decorated = [dict(cluster) for cluster in clusters]
        if not decorated:
            return decorated

        references = await self._load_references(start=start, end=end)
        if not references:
            return decorated

        for cluster in decorated:
            match = self._best_match(cluster, references)
            if match is None:
                continue
            cluster["experience_id"] = match.reference.experience_id
            cluster["experience_title"] = match.reference.title
            if match.chapter is not None:
                cluster["experience_chapter_id"] = match.chapter.chapter_id
                cluster["experience_chapter_title"] = match.chapter.title
        return decorated

    async def _load_references(
        self,
        *,
        start: float,
        end: float,
    ) -> list[_ExperienceReference]:
        list_experiences = getattr(self._l2, "list_experiences", None)
        list_members = getattr(self._l2, "list_experience_members", None)
        if not callable(list_experiences) or not callable(list_members):
            return []

        experiences = await list_experiences(
            status="active",
            time_start=start,
            time_end=end,
            limit=200,
        )
        references: list[_ExperienceReference] = []
        list_chapters = getattr(self._l2, "list_experience_chapters", None)
        for experience in experiences:
            if str(experience.get("status") or "") != "active":
                continue
            experience_id = str(experience.get("experience_id") or "").strip()
            if not experience_id:
                continue

            members = await list_members(experience_id=experience_id, limit=500)
            episode_ids, event_ids = self._member_ids(members)
            if not episode_ids and not event_ids:
                continue

            chapters = (
                await list_chapters(experience_id=experience_id) if callable(list_chapters) else []
            )
            chapter_references = tuple(
                reference
                for reference in (self._chapter_reference(chapter) for chapter in chapters)
                if reference.chapter_id
            )
            references.append(
                _ExperienceReference(
                    experience_id=experience_id,
                    title=str(
                        experience.get("user_label") or experience.get("title") or ""
                    ).strip(),
                    episode_ids=frozenset(episode_ids),
                    event_ids=frozenset(event_ids),
                    chapters=chapter_references,
                )
            )
        return references

    @staticmethod
    def _member_ids(members: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
        episode_ids: set[str] = set()
        event_ids: set[str] = set()
        for member in members:
            if str(member.get("role") or "") == "excluded":
                continue
            member_id = str(member.get("member_id") or "").strip()
            if not member_id:
                continue
            member_type = str(member.get("member_type") or "")
            if member_type == "episode":
                episode_ids.add(member_id)
            elif member_type == "event":
                event_ids.add(member_id)
        return episode_ids, event_ids

    @staticmethod
    def _chapter_reference(chapter: dict[str, Any]) -> _ExperienceChapterReference:
        return _ExperienceChapterReference(
            chapter_id=str(chapter.get("chapter_id") or "").strip(),
            title=str(chapter.get("title") or "").strip(),
            episode_ids=frozenset(
                str(episode_id).strip()
                for episode_id in chapter.get("episode_ids") or []
                if str(episode_id).strip()
            ),
            event_ids=frozenset(
                str(event_id).strip()
                for event_id in chapter.get("event_ids") or []
                if str(event_id).strip()
            ),
        )

    def _best_match(
        self,
        cluster: dict[str, Any],
        references: list[_ExperienceReference],
    ) -> _ExperienceMatch | None:
        episode_id = str(cluster.get("episode_id") or "").strip()
        event_ids = {
            str(event_id).strip()
            for event_id in cluster.get("representative_event_ids") or []
            if str(event_id).strip()
        }
        matches: list[_ExperienceMatch] = []
        for reference in references:
            episode_member_match = bool(episode_id and episode_id in reference.episode_ids)
            event_member_matches = len(event_ids & reference.event_ids)
            if not episode_member_match and event_member_matches == 0:
                continue

            chapter = self._best_chapter(
                reference.chapters,
                episode_id=episode_id,
                event_ids=event_ids,
            )
            matches.append(
                _ExperienceMatch(
                    reference=reference,
                    chapter=chapter,
                    score=(
                        1 if chapter is not None else 0,
                        1 if episode_member_match else 0,
                        event_member_matches,
                    ),
                )
            )
        return max(matches, key=lambda match: match.score, default=None)

    @staticmethod
    def _best_chapter(
        chapters: tuple[_ExperienceChapterReference, ...],
        *,
        episode_id: str,
        event_ids: set[str],
    ) -> _ExperienceChapterReference | None:
        best: _ExperienceChapterReference | None = None
        best_score = (0, 0)
        for chapter in chapters:
            episode_match = bool(episode_id and episode_id in chapter.episode_ids)
            event_matches = len(event_ids & chapter.event_ids)
            score = (1 if episode_match else 0, event_matches)
            if score > best_score:
                best = chapter
                best_score = score
        return best


__all__ = ["TimelineExperienceLinker"]
