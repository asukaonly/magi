"""
配置管理模块 - YAML配置加载器
"""
import os
import logging
import yaml
from pathlib import Path
from typing import Optional, Dict, Any
from .models import Config, AgentConfig

logger = logging.getLogger(__name__)


class ConfigLoader:
    """配置加载器"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器

        Args:
            config_path: 配置文件路径，默认为 ./configs/agent.yaml
        """
        if config_path is None:
            # 尝试多个默认位置（支持从不同目录运行）
            possible_paths = [
                "./configs/agent.yaml",           # 从项目根目录运行
                "../configs/agent.yaml",          # 从 backend 目录运行
                "./agent.yaml",                   # 当前目录
                "/etc/magi/agent.yaml",           # 系统级配置
            ]

            for default_path in possible_paths:
                # 转换为绝对路径
                abs_path = os.path.abspath(default_path)
                if os.path.exists(abs_path):
                    config_path = abs_path
                    logger.info(f"Found config file: {config_path}")
                    break

        self.config_path = config_path
        self._config: Optional[Config] = None

    def load(self) -> Config:
        """
        加载配置文件

        Returns:
            Config: 配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置文件格式错误
        """
        if self._config is not None:
            return self._config

        if self.config_path is None or not os.path.exists(self.config_path):
            # 返回默认配置
            self._config = self._load_default_config()
            return self._config

        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # 环境变量替换
        data = self._substitute_env_vars(data)

        # 验证并创建配置对象
        self._config = Config(**data)
        return self._config

    def _load_default_config(self) -> Config:
        """加载默认配置"""
        return Config(
            agent=AgentConfig(
                name="magi-agent",
            )
        )

    def _substitute_env_vars(self, data: Any) -> Any:
        """
        递归替换配置中的环境变量

        支持格式：${ENV_VAR} 或 ${ENV_VAR:default_value}

        Args:
            data: 配置数据

        Returns:
            替换后的数据
        """
        if isinstance(data, str):
            # 替换环境变量
            if "${" in data and "}" in data:
                # 找到所有 ${...} 模式
                import re
                pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

                def replace_var(match):
                    var_name = match.group(1)
                    default_value = match.group(2) if match.group(2) is not None else ""
                    return os.getenv(var_name, default_value)

                result = re.sub(pattern, replace_var, data)
                # 如果替换后还是环境变量格式且值为空，返回空字符串
                if result.startswith("${") and not os.getenv(data[2:data.index('}')]):
                    return ""
                return result
            return data

        elif isinstance(data, dict):
            return {k: self._substitute_env_vars(v) for k, v in data.items()}

        elif isinstance(data, list):
            return [self._substitute_env_vars(item) for item in data]

        else:
            return data

    def reload(self) -> Config:
        """重新加载配置"""
        self._config = None
        return self.load()


# 全局配置加载器实例
_global_loader: Optional[ConfigLoader] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """
    获取全局配置

    Args:
        config_path: 配置文件路径（仅首次调用有效）

    Returns:
        Config: 配置对象
    """
    global _global_loader

    if _global_loader is None:
        _global_loader = ConfigLoader(config_path)

    return _global_loader.load()


def reload_config() -> Config:
    """
    重新加载全局配置

    Returns:
        Config: 配置对象
    """
    global _global_loader

    if _global_loader is not None:
        return _global_loader.reload()

    return get_config()
