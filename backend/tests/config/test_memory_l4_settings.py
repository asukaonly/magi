from __future__ import annotations
from magi.config.memory_models import MemoryL4Settings as MM
from magi.config.models import MemoryL4Settings as MO


def test_memory_models_has_new_fields():
    s = MM()
    assert s.maintenance_enabled is True
    assert s.breaker_open_timeout_seconds == 600
    assert s.breaker_halfopen_idle_seconds == 1800
    assert s.inactive_skill_retention_days == 30
    assert s.inactive_skill_min_attempts == 5


def test_models_has_new_fields():
    s = MO()
    assert s.maintenance_enabled is True
    assert s.breaker_open_timeout_seconds == 600
    assert s.breaker_halfopen_idle_seconds == 1800
    assert s.inactive_skill_retention_days == 30
    assert s.inactive_skill_min_attempts == 5
