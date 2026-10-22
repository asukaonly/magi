"""Host-owned authorship policy for personal document source categories."""

from __future__ import annotations

# These are semantic source categories, independent of plugin/connection IDs.
_DOCUMENT_EVENTS_BY_SOURCE = {
    "local_documents": frozenset({"source_event"}),
    "obsidian_vault": frozenset({"source_event"}),
    "manual_entry": frozenset({"manual_entry.note"}),
}

PERSONAL_DOCUMENT_INSTRUCTIONS = """\
These events contain personal notes or diary documents, not live chat turns.
Read the complete document for explicit self-reports. Use user:self only for a
proposition that the author asserts about themselves. Preserve its negation,
conditions, subject and time. A mention, wikilink, tag, reading excerpt or an
assistant's suggestion does not establish the author's preference or intention.
Keep third-party facts attached to that third party; do not turn their identity,
preferences or plans into the user's profile. Mark another speaker's statement
as quoted, and examples, conditional wishes and uncertain statements with their
corresponding assertion_mode. Inspect attribution in the surrounding prose,
including quotations without Markdown formatting. Headings and colon labels
alone do not determine authorship. Extract an explicit communication preference
such as "请叫我小明" as a self-report even though it is phrased as a request.
File modification, capture and sync times do not prove currentness. Preserve time
expressions as written; let the host apply source-time and retention policies.
"""


def is_personal_document(*, source: str, event_type: str) -> bool:
    """Identify document evidence without granting user authorship or write access."""
    kind = event_type.strip().casefold()
    if kind == "history_import.document":
        return True
    return kind in _DOCUMENT_EVENTS_BY_SOURCE.get(source.strip().casefold(), frozenset())
