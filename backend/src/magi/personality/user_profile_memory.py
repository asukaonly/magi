"""User profile store — lightweight per-user identity and preference cache.

This module persists basic user profile data (name, preferences) that the
prompt assembler injects into context.  Relationship metrics (trust, depth,
interaction counts) are owned by GrowthMemory and are intentionally *not*
tracked here to avoid duplication.
"""
import logging
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class UserProfile:
    """Per-user profile data."""

    def __init__(
        self,
        user_id: str,
        name: str = "user",
        nickname: str = "",
        interests: List[str] = None,
        habits: List[str] = None,
        personality_traits: List[str] = None,
        communication_style: str = "friendly",
        relationship_depth: float = 0.0,
        trust_level: float = 0.5,
        first_met: float = None,
        last_interacted: float = None,
        total_interactions: int = 0,
        preferences: Dict[str, Any] = None,
        important_events: List[Dict[str, Any]] = None,
        notes: str = "",
    ):
        self.user_id = user_id
        self.name = name
        self.nickname = nickname
        self.interests = interests or []
        self.habits = habits or []
        self.personality_traits = personality_traits or []
        self.communication_style = communication_style
        self.relationship_depth = relationship_depth
        self.trust_level = trust_level
        self.first_met = first_met or time.time()
        self.last_interacted = last_interacted or time.time()
        self.total_interactions = total_interactions
        self.preferences = preferences or {}
        self.important_events = important_events or []
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "nickname": self.nickname,
            "interests": self.interests,
            "habits": self.habits,
            "personality_traits": self.personality_traits,
            "communication_style": self.communication_style,
            "relationship_depth": self.relationship_depth,
            "trust_level": self.trust_level,
            "first_met": self.first_met,
            "last_interacted": self.last_interacted,
            "total_interactions": self.total_interactions,
            "preferences": self.preferences,
            "important_events": self.important_events,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """Create from dictionary"""
        return cls(**data)


class _UserProfileFormatter:
    """Markdown serializer for UserProfile."""

    @staticmethod
    def to_markdown(profile: UserProfile) -> str:
        """Convert profile to Markdown format"""
        lines = [
            f"# {profile.name}",
            "",
            f"> userid: `{profile.user_id}`",
            f"> Nickname: {profile.nickname or 'None'}",
            f"> relationshipdepth: `{profile.relationship_depth:.2f}`",
            f"> Trust level: `{profile.trust_level:.2f}`",
            f"> Interaction count: `{profile.total_interactions}`",
            f"> First met: `{datetime.fromtimestamp(profile.first_met).strftime('%Y-%m-%d %H:%M')}`",
            f"> Last interaction: `{datetime.fromtimestamp(profile.last_interacted).strftime('%Y-%m-%d %H:%M')}`",
            "",
            "## Basic Info",
            "",
            f"- **Name**: {profile.name}",
            f"- **Nickname**: {profile.nickname or 'None'}",
            f"- **Communication style**: {profile.communication_style}",
            "",
            "## Interests & Hobbies",
            "",
        ]

        if profile.interests:
            for interest in profile.interests:
                lines.append(f"- {interest}")
        else:
            lines.append("*No records yet*")

        lines.extend([
            "",
            "## Habits & Traits",
            "",
        ])

        if profile.habits:
            for habit in profile.habits:
                lines.append(f"- {habit}")
        else:
            lines.append("*No records yet*")

        lines.extend([
            "",
            "## Character Traits",
            "",
        ])

        if profile.personality_traits:
            for trait in profile.personality_traits:
                lines.append(f"- {trait}")
        else:
            lines.append("*No records yet*")

        # preferenceSetting
        if profile.preferences:
            lines.extend([
                "",
                "## preferenceSetting",
                "",
            ])
            for key, value in profile.preferences.items():
                lines.append(f"- **{key}**: {value}")

        # Internal note.
        if profile.important_events:
            lines.extend([
                "",
                "## Important Events",
                "",
            ])
            for event in profile.important_events[-10:]:  # Last 10 entries
                timestamp = event.get("timestamp", 0)
                date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d') if timestamp else "Unknown"
                lines.append(f"- **{date_str}**: {event.get('description', event.get('title', 'No description'))}")

        # note
        if profile.notes:
            lines.extend([
                "",
                "## note",
                "",
                profile.notes,
            ])

        return "\n".join(lines)

    @staticmethod
    def parse_markdown(content: str, user_id: str) -> UserProfile:
        """Parse profile from Markdown content"""
        import re

        data = {
            "user_id": user_id,
            "interests": [],
            "habits": [],
            "personality_traits": [],
            "preferences": {},
            "important_events": [],
        }

        # Internal note.
        name_match = re.search(r'^# (.+)$', content, re.MULTILINE)
        if name_match:
            data["name"] = name_match.group(1).strip()

        # parsemetadata
        nickname_match = re.search(r'Nickname: ([^\n]+)', content)
        relationship_match = re.search(r'relationshipdepth: `([\d.]+)`', content)
        trust_match = re.search(r'Trust level: `([\d.]+)`', content)
        interactions_match = re.search(r'Interaction count: `(\d+)`', content)
        first_met_match = re.search(r'First met: `([\d\-: ]+)`', content)
        last_interacted_match = re.search(r'Last interaction: `([\d\-: ]+)`', content)
        style_match = re.search(r'\*\*Communication style\*\*: ([^\n]+)', content)

        if nickname_match:
            data["nickname"] = nickname_match.group(1).strip()
        if relationship_match:
            data["relationship_depth"] = float(relationship_match.group(1))
        if trust_match:
            data["trust_level"] = float(trust_match.group(1))
        if interactions_match:
            data["total_interactions"] = int(interactions_match.group(1))
        if style_match:
            data["communication_style"] = style_match.group(1).strip()
        if first_met_match:
            try:
                data["first_met"] = datetime.strptime(first_met_match.group(1), '%Y-%m-%d %H:%M').timestamp()
            except:
                pass
        if last_interacted_match:
            try:
                data["last_interacted"] = datetime.strptime(last_interacted_match.group(1), '%Y-%m-%d %H:%M').timestamp()
            except:
                pass

        # parselistContent
        current_section = None
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('>'):
                continue

            if line.startswith('## '):
                section = line[3:].strip()
                if 'Interests' in section:
                    current_section = 'interests'
                elif 'habit' in section:
                    current_section = 'habits'
                elif 'character' in section:
                    current_section = 'personality'
                elif 'preference' in section:
                    current_section = 'preferences'
                elif 'event' in section:
                    current_section = 'events'
                elif 'note' in section:
                    current_section = 'notes'
                else:
                    current_section = None
            elif line.startswith('- '):
                content = line[2:].strip()
                if current_section == 'interests':
                    data["interests"].append(content)
                elif current_section == 'habits':
                    data["habits"].append(content)
                elif current_section == 'personality':
                    data["personality_traits"].append(content)
                elif current_section == 'events':
                    # parseevent: **2024-01-01**: eventDescription
                    event_match = re.match(r'\*\*([\d\-:]+)\*\*:\s*(.+)', content)
                    if event_match:
                        try:
                            event_timestamp = datetime.strptime(event_match.group(1), '%Y-%m-%d').timestamp()
                            data["important_events"].append({
                                "timestamp": event_timestamp,
                                "description": event_match.group(2),
                            })
                        except:
                            pass

        return UserProfile.from_dict(data)


# Backward-compatible alias.
OtherProfile = UserProfile


class UserProfileMemory:
    """Lightweight per-user profile store (Markdown files)."""

    def __init__(self, others_dir: str = None):
        """
        Internal note.

        Args:
            Internal note.
        """
        if others_dir is None:
            from ..utils.runtime import get_runtime_paths
            runtime_paths = get_runtime_paths()
            self.others_dir = runtime_paths.others_dir
        else:
            self.others_dir = Path(others_dir)

        # Internal note.
        self.others_dir.mkdir(parents=True, exist_ok=True)

        self._cache: Dict[str, UserProfile] = {}
        self.formatter = _UserProfileFormatter()

    def _get_profile_path(self, user_id: str) -> Path:
        """Get user profile file path"""
        # Internal note.
        safe_name = user_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.others_dir / f"{safe_name}.md"

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """
        Internal note.

        Args:
            user_id: userid

        Returns:
            Internal note.
        """
        # Internal note.
        if user_id in self._cache:
            return self._cache[user_id]

        profile_path = self._get_profile_path(user_id)

        if not profile_path.exists():
            return None

        try:
            content = profile_path.read_text(encoding='utf-8')
            profile = self.formatter.parse_markdown(content, user_id)
            self._cache[user_id] = profile
            return profile
        except Exception as e:
            logger.error(f"Failed to load profile for {user_id}: {e}")
            return None

    def save_profile(self, profile: UserProfile) -> bool:
        """
        Internal note.

        Args:
            Internal note.

        Returns:
            is notsavesuccess
        """
        try:
            profile_path = self._get_profile_path(profile.user_id)
            content = self.formatter.to_markdown(profile)
            profile_path.write_text(content, encoding='utf-8')
            self._cache[profile.user_id] = profile
            logger.info(f"Profile saved for {profile.user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save profile for {profile.user_id}: {e}")
            return False

    def update_interaction(
        self,
        user_id: str,
        interaction_type: str = "chat",
        outcome: str = "neutral",
        notes: str = "",
    ) -> UserProfile:
        """Record an interaction and persist the profile.

        Note: relationship metrics (trust_level, relationship_depth) are
        intentionally **not** updated here — GrowthMemory owns those.
        """
        profile = self.get_profile(user_id)

        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                name=user_id,
            )

        profile.total_interactions += 1
        profile.last_interacted = time.time()

        self.save_profile(profile)
        return profile

    def list_profiles(self) -> List[UserProfile]:
        """
        Internal note.

        Returns:
            Internal note.
        """
        profiles = []
        for md_file in self.others_dir.glob("*.md"):
            user_id = md_file.stem
            # Internal note.
            # Internal note.
            profile = self.get_profile(user_id)
            if profile:
                profiles.append(profile)

        # Internal note.
        profiles.sort(key=lambda p: p.last_interacted, reverse=True)
        return profiles

    def delete_profile(self, user_id: str) -> bool:
        """
        Internal note.

        Args:
            user_id: userid

        Returns:
            is notdeletesuccess
        """
        try:
            profile_path = self._get_profile_path(user_id)
            if profile_path.exists():
                profile_path.unlink()
            if user_id in self._cache:
                del self._cache[user_id]
            logger.info(f"Profile deleted for {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete profile for {user_id}: {e}")
            return False

    def clear_cache(self):
        """Clear the in-memory profile cache."""
        self._cache.clear()


# Backward-compatible alias.
OtherMemory = UserProfileMemory
