"""Typed chat session records shared by memory and conversation queries."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from magi_plugin_sdk.storage_models.chat_sessions import (
    ChatSessionRecord,
    create_chat_session_record,
)
