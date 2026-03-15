"""
Tool version management.

Implements tool versioning and compatibility checks.
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class ToolVersion:
    """Tool version info."""
    version: str
    tool_class: type  # Tool class
    registered_at: datetime = field(default_factory=datetime.now)
    deprecation_date: Optional[datetime] = None
    is_deprecated: bool = False
    migration_guide: Optional[str] = None
    breaking_changes: List[str] = field(default_factory=list)


@dataclass
class VersionCompatibility:
    """Version compatibility info."""
    min_version: str
    max_version: Optional[str] = None
    compatible: bool = True
    notes: str = ""


class ToolVersionManager:
    """
    Tool version manager.

    Manages multiple versions of tools and version upgrade compatibility.
    """

    def __init__(self):
        # {tool_name: {version: ToolVersion}}
        self.versions: Dict[str, Dict[str, ToolVersion]] = {}

        # {tool_name: active_version}
        self.active_versions: Dict[str, str] = {}

    def register_version(
        self,
        tool_name: str,
        version: str,
        tool_class: type,
        is_active: bool = True,
        deprecation_date: Optional[datetime] = None,
        migration_guide: Optional[str] = None,
        breaking_changes: Optional[List[str]] = None
    ) -> None:
        """
        Register tool version.

        Args:
            tool_name: Tool name.
            version: Version number (SemVer).
            tool_class: Tool class.
            is_active: Whether to set as active version.
            deprecation_date: Deprecation date.
            migration_guide: Migration guide.
            breaking_changes: List of breaking changes.
        """
        if tool_name not in self.versions:
            self.versions[tool_name] = {}

        # Check if version already exists
        if version in self.versions[tool_name]:
            logger.warning(f"Version {version} of tool {tool_name} already exists, overwriting")

        tool_version = ToolVersion(
            version=version,
            tool_class=tool_class,
            deprecation_date=deprecation_date,
            is_deprecated=deprecation_date is not None,
            migration_guide=migration_guide,
            breaking_changes=breaking_changes or []
        )

        self.versions[tool_name][version] = tool_version

        # Set as active version
        if is_active:
            self.active_versions[tool_name] = version
            logger.info(f"Set version {version} as active for tool {tool_name}")

        logger.info(f"Registered version {version} for tool {tool_name}")

    def get_active_version(self, tool_name: str) -> Optional[str]:
        """
        Get active version of a tool.

        Args:
            tool_name: Tool name.

        Returns:
            Version number or None.
        """
        return self.active_versions.get(tool_name)

    def get_tool_class(self, tool_name: str, version: Optional[str] = None) -> Optional[type]:
        """
        Get tool class.

        Args:
            tool_name: Tool name.
            version: Version number (None for active version).

        Returns:
            Tool class or None.
        """
        if tool_name not in self.versions:
            return None

        if version is None:
            version = self.active_versions.get(tool_name)

        if version and version in self.versions[tool_name]:
            return self.versions[tool_name][version].tool_class

        return None

    def list_versions(self, tool_name: str) -> List[ToolVersion]:
        """
        List all versions of a tool.

        Args:
            tool_name: Tool name.

        Returns:
            List of versions (sorted by version number).
        """
        if tool_name not in self.versions:
            return []

        versions = list(self.versions[tool_name].values())
        # Sort by version number (semantic version comparison)
        versions.sort(key=lambda v: self._parse_version(v.version))
        return versions

    def is_deprecated(self, tool_name: str, version: Optional[str] = None) -> bool:
        """
        Check if version is deprecated.

        Args:
            tool_name: Tool name.
            version: Version number (None to check active version).

        Returns:
            Whether deprecated.
        """
        if version is None:
            version = self.active_versions.get(tool_name)

        if not version or tool_name not in self.versions:
            return False

        return self.versions[tool_name][version].is_deprecated

    def check_compatibility(
        self,
        tool_name: str,
        required_version: str
    ) -> VersionCompatibility:
        """
        Check version compatibility.

        Args:
            tool_name: Tool name.
            required_version: Required version.

        Returns:
            Compatibility info.
        """
        active_version = self.active_versions.get(tool_name)

        if not active_version:
            return VersionCompatibility(
                min_version=required_version,
                compatible=False,
                notes=f"Tool {tool_name} has no active version"
            )

        # Simple version comparison (consider using packaging.version for semantic comparison)
        active_parsed = self._parse_version(active_version)
        required_parsed = self._parse_version(required_version)

        if active_parsed >= required_parsed:
            return VersionCompatibility(
                min_version=required_version,
                max_version=active_version,
                compatible=True,
                notes="Version is compatible"
            )
        else:
            return VersionCompatibility(
                min_version=required_version,
                compatible=False,
                notes=f"Active version {active_version} is less than required {required_version}"
            )

    def set_active_version(self, tool_name: str, version: str) -> bool:
        """
        Set active version.

        Args:
            tool_name: Tool name.
            version: Version number.

        Returns:
            Whether successful.
        """
        if tool_name not in self.versions or version not in self.versions[tool_name]:
            logger.warning(f"Version {version} of tool {tool_name} does not exist")
            return False

        old_version = self.active_versions.get(tool_name)
        self.active_versions[tool_name] = version

        logger.info(f"Switched tool {tool_name} from version {old_version} to {version}")
        return True

    def deprecate_version(
        self,
        tool_name: str,
        version: str,
        migration_guide: Optional[str] = None
    ) -> bool:
        """
        Deprecate a version.

        Args:
            tool_name: Tool name.
            version: Version number.
            migration_guide: Migration guide.

        Returns:
            Whether successful.
        """
        if tool_name not in self.versions or version not in self.versions[tool_name]:
            logger.warning(f"Version {version} of tool {tool_name} does not exist")
            return False

        tool_version = self.versions[tool_name][version]
        tool_version.is_deprecated = True
        tool_version.deprecation_date = datetime.now()
        tool_version.migration_guide = migration_guide

        logger.info(f"Deprecated version {version} of tool {tool_name}")
        return True

    def get_migration_guide(self, tool_name: str, from_version: str) -> Optional[str]:
        """
        Get migration guide.

        Args:
            tool_name: Tool name.
            from_version: Source version.

        Returns:
            Migration guide or None.
        """
        if tool_name not in self.versions or from_version not in self.versions[tool_name]:
            return None

        return self.versions[tool_name][from_version].migration_guide

    def get_breaking_changes(self, tool_name: str, from_version: str, to_version: Optional[str] = None) -> List[str]:
        """
        Get breaking changes.

        Args:
            tool_name: Tool name.
            from_version: Source version.
            to_version: Target version (None for active version).

        Returns:
            List of breaking changes.
        """
        if to_version is None:
            to_version = self.active_versions.get(tool_name)

        if not to_version or tool_name not in self.versions:
            return []

        # Simplified: return target version's breaking changes
        # Ideally compare all breaking changes between from_version and to_version
        if to_version in self.versions[tool_name]:
            return self.versions[tool_name][to_version].breaking_changes

        return []

    def _parse_version(self, version: str) -> tuple:
        """
        Parse version number.

        Simple implementation; consider using packaging.version.

        Args:
            version: Version string.

        Returns:
            (major, minor, patch)
        """
        try:
            parts = version.split(".")
            if len(parts) >= 3:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
            elif len(parts) == 2:
                return (int(parts[0]), int(parts[1]), 0)
            elif len(parts) == 1:
                return (int(parts[0]), 0, 0)
        except (ValueError, IndexError):
            pass

        return (0, 0, 0)

    def get_version_info(self, tool_name: str) -> Dict[str, Any]:
        """
        Get full version info for a tool.

        Args:
            tool_name: Tool name.

        Returns:
            Version info dictionary.
        """
        active_version = self.active_versions.get(tool_name)
        versions = self.list_versions(tool_name)

        return {
            "tool_name": tool_name,
            "active_version": active_version,
            "available_versions": [v.version for v in versions],
            "total_versions": len(versions),
            "deprecated_versions": [v.version for v in versions if v.is_deprecated],
            "has_deprecated": any(v.is_deprecated for v in versions),
        }
