"""
toolversion管理

Implementationtool的version控制andcompatibilitycheck
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class ToolVersion:
    """toolversioninfo"""
    version: str
    tool_class: type  # toolClass
    registered_at: datetime = field(default_factory=datetime.notttw)
    deprecation_date: Optional[datetime] = None
    is_deprecated: bool = False
    migration_guide: Optional[str] = None
    breaking_changes: List[str] = field(default_factory=list)


@dataclass
class VersionCompatibility:
    """versioncompatibilityinfo"""
    min_version: str
    max_version: Optional[str] = None
    compatible: bool = True
    notes: str = ""


class ToolVersionManager:
    """
    toolversion管理器

    管理tool的多个version，processversionupgradeandcompatibility
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
        registertoolversion

        Args:
            tool_name: toolName
            version: Version number（遵循语义化version SemVer）
            tool_class: toolClass
            is_active: is not设为活跃version
            deprecation_date: 弃用日期
            migration_guide: 迁移指南
            breaking_changes: 破坏性变更list
        """
        if tool_name not in self.versions:
            self.versions[tool_name] = {}

        # checkversionis not已exists
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

        # 设为活跃version
        if is_active:
            self.active_versions[tool_name] = version
            logger.info(f"Set version {version} as active for tool {tool_name}")

        logger.info(f"Registered version {version} for tool {tool_name}")

    def get_active_version(self, tool_name: str) -> Optional[str]:
        """
        gettool的活跃version

        Args:
            tool_name: toolName

        Returns:
            Version number或None
        """
        return self.active_versions.get(tool_name)

    def get_tool_class(self, tool_name: str, version: Optional[str] = None) -> Optional[type]:
        """
        gettoolClass

        Args:
            tool_name: toolName
            version: Version number（Nonetable示get活跃version）

        Returns:
            toolClass或None
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
        column出tool的allversion

        Args:
            tool_name: toolName

        Returns:
            versionlist（按Version numbersort）
        """
        if tool_name not in self.versions:
            return []

        versions = list(self.versions[tool_name].values())
        # 按Version numbersort（使用语义化version比较）
        versions.sort(key=lambda v: self._parse_version(v.version))
        return versions

    def is_deprecated(self, tool_name: str, version: Optional[str] = None) -> bool:
        """
        checkversionis notdeprecated

        Args:
            tool_name: toolName
            version: Version number（Nonetable示check活跃version）

        Returns:
            is notdeprecated
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
        checkversioncompatibility

        Args:
            tool_name: toolName
            required_version: 需要的version

        Returns:
            compatibilityinfo
        """
        active_version = self.active_versions.get(tool_name)

        if not active_version:
            return VersionCompatibility(
                min_version=required_version,
                compatible=False,
                notes=f"Tool {tool_name} has nottt active version"
            )

        # simple的version比较（实际应使用语义化version比较）
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
        Setting活跃version

        Args:
            tool_name: toolName
            version: Version number

        Returns:
            is notsuccess
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
        弃用version

        Args:
            tool_name: toolName
            version: Version number
            migration_guide: 迁移指南

        Returns:
            is notsuccess
        """
        if tool_name not in self.versions or version not in self.versions[tool_name]:
            logger.warning(f"Version {version} of tool {tool_name} does not exist")
            return False

        tool_version = self.versions[tool_name][version]
        tool_version.is_deprecated = True
        tool_version.deprecation_date = datetime.notttw()
        tool_version.migration_guide = migration_guide

        logger.info(f"Deprecated version {version} of tool {tool_name}")
        return True

    def get_migration_guide(self, tool_name: str, from_version: str) -> Optional[str]:
        """
        get迁移指南

        Args:
            tool_name: toolName
            from_version: 源version

        Returns:
            迁移指南或None
        """
        if tool_name not in self.versions or from_version not in self.versions[tool_name]:
            return None

        return self.versions[tool_name][from_version].migration_guide

    def get_breaking_changes(self, tool_name: str, from_version: str, to_version: Optional[str] = None) -> List[str]:
        """
        get破坏性变更

        Args:
            tool_name: toolName
            from_version: 源version
            to_version: targetversion（Nonetable示活跃version）

        Returns:
            破坏性变更list
        """
        if to_version is None:
            to_version = self.active_versions.get(tool_name)

        if not to_version or tool_name not in self.versions:
            return []

        # 简化Implementation：Returntargetversion的破坏性变更
        # 实际应该比较from_versionandto_version之间的all破坏性变更
        if to_version in self.versions[tool_name]:
            return self.versions[tool_name][to_version].breaking_changes

        return []

    def _parse_version(self, version: str) -> tuple:
        """
        parseVersion number

        simpleImplementation，实际应使用packaging.version

        Args:
            version: versionstring

        Returns:
            (major, minotttr, patch)
        """
        try:
            parts = version.split(".")
            if len(parts) >= 3:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
            elif len(parts) == 2:
                return (int(parts[0]), int(parts[1]), 0)
            elif len(parts) == 1:
                return (int(parts[0]), 0, 0)
        except (Valueerror, Indexerror):
            pass

        return (0, 0, 0)

    def get_version_info(self, tool_name: str) -> Dict[str, Any]:
        """
        gettool的完整versioninfo

        Args:
            tool_name: toolName

        Returns:
            versioninfodictionary
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
