"""
Internal note.

Internal note.
Internal note.
- relationshipdepth
Internal note.
Internal note.
"""
import logging
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime
from .adaptive_profile_updater import AdaptiveProfileUpdater

logger = logging.getLogger(__name__)


# Internal note.

class OtherProfile:
    """他人画像"""

    def __init__(
        self,
        user_id: str,
        name: str = "user",
        nickname: str = "",
        interests: List[str] = None,
        habits: List[str] = None,
        personality_traits: List[str] = None,
        communication_style: str = "友好",
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
        """convert为dictionary"""
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
    def from_dict(cls, data: Dict[str, Any]) -> "OtherProfile":
        """从dictionarycreate"""
        return cls(**data)


# Internal note.

class OtherProfileFormatter:
    """他人画像 Markdown format化器"""

    @staticmethod
    def to_markdown(profile: OtherProfile) -> str:
        """将画像convert为 Markdown format"""
        lines = [
            f"# {profile.name}",
            "",
            f"> userid: `{profile.user_id}`",
            f"> 昵称: {profile.nickname or '无'}",
            f"> relationshipdepth: `{profile.relationship_depth:.2f}`",
            f"> trust度: `{profile.trust_level:.2f}`",
            f"> 交互count: `{profile.total_interactions}`",
            f"> 初次见面: `{datetime.fromtimestamp(profile.first_met).strftime('%Y-%m-%d %H:%M')}`",
            f"> 最近互动: `{datetime.fromtimestamp(profile.last_interacted).strftime('%Y-%m-%d %H:%M')}`",
            "",
            "## 基本info",
            "",
            f"- **姓名**: {profile.name}",
            f"- **昵称**: {profile.nickname or '无'}",
            f"- **沟通style**: {profile.communication_style}",
            "",
            "## 兴趣爱好",
            "",
        ]

        if profile.interests:
            for interest in profile.interests:
                lines.append(f"- {interest}")
        else:
            lines.append("*暂无record*")

        lines.extend([
            "",
            "## habit特点",
            "",
        ])

        if profile.habits:
            for habit in profile.habits:
                lines.append(f"- {habit}")
        else:
            lines.append("*暂无record*")

        lines.extend([
            "",
            "## character特征",
            "",
        ])

        if profile.personality_traits:
            for trait in profile.personality_traits:
                lines.append(f"- {trait}")
        else:
            lines.append("*暂无record*")

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
                "## 重要event",
                "",
            ])
            for event in profile.important_events[-10:]:  # 最近10条
                timestamp = event.get("timestamp", 0)
                date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d') if timestamp else "未知"
                lines.append(f"- **{date_str}**: {event.get('description', event.get('title', '无Description'))}")

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
    def parse_markdown(content: str, user_id: str) -> OtherProfile:
        """从 Markdown Contentparse画像"""
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
        nickname_match = re.search(r'昵称: ([^\n]+)', content)
        relationship_match = re.search(r'relationshipdepth: `([\d.]+)`', content)
        trust_match = re.search(r'trust度: `([\d.]+)`', content)
        interactions_match = re.search(r'交互count: `(\d+)`', content)
        first_met_match = re.search(r'初次见面: `([\d\-: ]+)`', content)
        last_interacted_match = re.search(r'最近互动: `([\d\-: ]+)`', content)
        style_match = re.search(r'\*\*沟通style\*\*: ([^\n]+)', content)

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
                if '兴趣' in section:
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

        return OtherProfile.from_dict(data)


# Internal note.

class OtherMemory:
    """
    Internal note.

    Internal note.
    """

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

        # Internal note.
        self._cache: Dict[str, OtherProfile] = {}

        self.formatter = OtherProfileFormatter()

    def _get_profile_path(self, user_id: str) -> Path:
        """getuser画像filepath"""
        # Internal note.
        safe_name = user_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.others_dir / f"{safe_name}.md"

    def get_profile(self, user_id: str) -> Optional[OtherProfile]:
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

    def save_profile(self, profile: OtherProfile) -> bool:
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
    ) -> OtherProfile:
        """
        Internal note.

        Args:
            user_id: userid
            Internal note.
            outcome: Result（positive/negative/neutral）
            notes: note

        Returns:
            Internal note.
        """
        profile = self.get_profile(user_id)

        if profile is None:
            # Internal note.
            profile = OtherProfile(
                user_id=user_id,
                name=user_id,
            )

        # Internal note.
        profile.total_interactions += 1
        profile.last_interacted = time.time()

        # Internal note.
        if outcome == "positive":
            profile.relationship_depth = min(1.0, profile.relationship_depth + 0.05)
            profile.trust_level = min(1.0, profile.trust_level + 0.03)
        elif outcome == "negative":
            profile.relationship_depth = max(0.0, profile.relationship_depth - 0.02)
            profile.trust_level = max(0.0, profile.trust_level - 0.01)

        # Internal note.
        if notes:
            profile.important_events.append({
                "timestamp": time.time(),
                "type": interaction_type,
                "description": notes,
            })
            # Internal note.
            if len(profile.important_events) > 50:
                profile.important_events = profile.important_events[-50:]

        self.save_profile(profile)
        return profile

    def update_profile_from_conversation(
        self,
        user_id: str,
        conversation_summary: str,
        extracted_info: Dict[str, Any] = None,
        significant_change: bool = False,
        force: bool = False,
    ) -> OtherProfile:
        """
        Internal note.

        Args:
            user_id: userid
            conversation_summary: dialoguesummary
            Internal note.

        Returns:
            Internal note.
        """
        profile = self.get_profile(user_id)

        if profile is None:
            profile = OtherProfile(
                user_id=user_id,
                name=extracted_info.get("name", user_id) if extracted_info else user_id,
            )

        # Track interaction before adaptive update decision.
        profile.total_interactions += 1
        profile.last_interacted = time.time()

        updater_state = {}
        if isinstance(profile.preferences, dict):
            updater_state = profile.preferences.get("_adaptive_updater", {}) or {}
        updater = AdaptiveProfileUpdater.from_dict(updater_state)
        updater.record_interaction()

        should_update = force or updater.should_update(
            total_interactions=profile.total_interactions,
            significant_change=significant_change,
        )

        if not should_update:
            profile.preferences["_adaptive_updater"] = updater.to_dict()
            self.save_profile(profile)
            return profile

        if extracted_info:
            if extracted_info.get("interests"):
                new_interests = [i for i in extracted_info["interests"] if i not in profile.interests]
                profile.interests.extend(new_interests)

            if extracted_info.get("habits"):
                new_habits = [h for h in extracted_info["habits"] if h not in profile.habits]
                profile.habits.extend(new_habits)

            if extracted_info.get("personality_traits"):
                new_traits = [t for t in extracted_info["personality_traits"] if t not in profile.personality_traits]
                profile.personality_traits.extend(new_traits)

            if extracted_info.get("name"):
                profile.name = extracted_info["name"]

            if extracted_info.get("nickname"):
                profile.nickname = extracted_info["nickname"]

            if extracted_info.get("communication_style"):
                profile.communication_style = extracted_info["communication_style"]

            # updatepreference
            if extracted_info.get("preferences"):
                profile.preferences.update(extracted_info["preferences"])
        updater.record_update()
        profile.preferences["_adaptive_updater"] = updater.to_dict()

        self.save_profile(profile)
        return profile

    def list_profiles(self) -> List[OtherProfile]:
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
        """clearcache"""
        self._cache.clear()
