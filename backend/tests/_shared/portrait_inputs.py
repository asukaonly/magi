"""Pathless portrait input ports for policy-focused tests."""

from magi.memory.l2.assertion_display import decorate_assertion_display
from magi.memory.l2.claims.self_reports import SelfReportEvidenceBatch


class EmptySelfReports:
    async def load(self, **kwargs):
        return SelfReportEvidenceBatch()

    async def latest_change_at(self, **kwargs):
        return 0.0


class PortraitPresentation:
    async def decorate_assertions(self, assertions):
        return await decorate_assertion_display(None, assertions)


class PortraitInputStub:
    self_reports = EmptySelfReports()
    presentation = PortraitPresentation()
