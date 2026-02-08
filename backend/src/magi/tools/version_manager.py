"""
工具版本管理

实现工具的版本控制和兼容性检查
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class ToolVersion:
    """工具版本信息"""
    version: str
    tool_class: type  # 工具类
    registered_at: datetime = field(default_factory=datetime.now)
    deprecation_date: Optional[datetime] = None
    is_deprecated: bool = False
    migration_guide: Optional[str] = None
    breaking_changes: List[str] = field(default_factory=list)


@dataclass
class VersionCompatibility:
    """版本兼容性信息"""
    min_version: str
    max_version: Optional[str] = None
    compatible: bool = True
    notes: str = ""


class ToolVersionManager:
    """
    工具版本管理器

    管理工具的多个版本，处理版本升级和兼容性
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
        注册工具版本

        Args:
            tool_name: 工具名称
            version: 版本号（遵循语义化版本 SemVer）
            tool_class: 工具类
            is_active: 是否设为活跃版本
            deprecation_date: 弃用日期
            migration_guide: 迁移指南
            breaking_changes: 破坏性变更列表
        """
        if tool_name not in self.versions:
            self.versions[tool_name] = {}

        # 检查版本是否已存在
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

        # 设为活跃版本
        if is_active:
            self.active_versions[tool_name] = version
            logger.info(f"Set version {version} as active for tool {tool_name}")

        logger.info(f"Registered version {version} for tool {tool_name}")

    def get_active_version(self, tool_name: str) -> Optional[str]:
        """
        获取工具的活跃版本

        Args:
            tool_name: 工具名称

        Returns:
            版本号或None
        """
        return self.active_versions.get(tool_name)

    def get_tool_class(self, tool_name: str, version: Optional[str] = None) -> Optional[type]:
        """
        获取工具类

        Args:
            tool_name: 工具名称
            version: 版本号（None表示获取活跃版本）

        Returns:
            工具类或None
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
        列出工具的所有版本

        Args:
            tool_name: 工具名称

        Returns:
            版本列表（按版本号排序）
        """
        if tool_name not in self.versions:
            return []

        versions = list(self.versions[tool_name].values())
        # 按版本号排序（使用语义化版本比较）
        versions.sort(key=lambda v: self._parse_version(v.version))
        return versions

    def is_deprecated(self, tool_name: str, version: Optional[str] = None) -> bool:
        """
        检查版本是否已弃用

        Args:
            tool_name: 工具名称
            version: 版本号（None表示检查活跃版本）

        Returns:
            是否已弃用
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
        检查版本兼容性

        Args:
            tool_name: 工具名称
            required_version: 需要的版本

        Returns:
            兼容性信息
        """
        active_version = self.active_versions.get(tool_name)

        if not active_version:
            return VersionCompatibility(
                min_version=required_version,
                compatible=False,
                notes=f"Tool {tool_name} has no active version"
            )

        # 简单的版本比较（实际应使用语义化版本比较）
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
        设置活跃版本

        Args:
            tool_name: 工具名称
            version: 版本号

        Returns:
            是否成功
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
        弃用版本

        Args:
            tool_name: 工具名称
            version: 版本号
            migration_guide: 迁移指南

        Returns:
            是否成功
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
        获取迁移指南

        Args:
            tool_name: 工具名称
            from_version: 源版本

        Returns:
            迁移指南或None
        """
        if tool_name not in self.versions or from_version not in self.versions[tool_name]:
            return None

        return self.versions[tool_name][from_version].migration_guide

    def get_breaking_changes(self, tool_name: str, from_version: str, to_version: Optional[str] = None) -> List[str]:
        """
        获取破坏性变更

        Args:
            tool_name: 工具名称
            from_version: 源版本
            to_version: 目标版本（None表示活跃版本）

        Returns:
            破坏性变更列表
        """
        if to_version is None:
            to_version = self.active_versions.get(tool_name)

        if not to_version or tool_name not in self.versions:
            return []

        # 简化实现：返回目标版本的破坏性变更
        # 实际应该比较from_version和to_version之间的所有破坏性变更
        if to_version in self.versions[tool_name]:
            return self.versions[tool_name][to_version].breaking_changes

        return []

    def _parse_version(self, version: str) -> tuple:
        """
        解析版本号

        简单实现，实际应使用packaging.version

        Args:
            version: 版本字符串

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
        获取工具的完整版本信息

        Args:
            tool_name: 工具名称

        Returns:
            版本信息字典
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
