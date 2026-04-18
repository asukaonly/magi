"""PassthroughAssembler — wraps raw payload for summary/strategy modes."""

from __future__ import annotations

from dataclasses import asdict

from ..models import RetrievalPayload, RetrievalQuery
from .base import PassthroughEvidence


class PassthroughAssembler:
    """No special assembly; wrap the payload dict as-is."""

    def assemble(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> PassthroughEvidence:
        return PassthroughEvidence(payload=asdict(payload))
