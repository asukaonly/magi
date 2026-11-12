"""Canonical representation for L2-owned L1 entity-link projections."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence

from magi_plugin_sdk.storage_models.entity_links import (
    DesiredEntityLink,
    normalize_desired_entity_links,
    desired_entity_links_json,
    desired_entity_links_fingerprint,
    desired_entity_links_from_json,
    __all__,
)
