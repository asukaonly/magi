"""Removed orchestration strategy helper module.

Routing now derives a typed agent orchestration plan from ``RouteDecision``.
This module stays empty so any attempt to use the old keyword-normalization
API fails loudly.
"""
from __future__ import annotations


__all__: list[str] = []
