"""
配置管理模块 - YAML配置加载器
"""
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any
from .models import Config, AgentConfig


class ConfigLoader:
    """配置加载器"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器

        Args:
            config_path: 配置文件路径，默认为 ./configs/agent.yaml
        """
        if config_path is None:
            # 尝试多个默认位置
            for default_path in [
                "./configs/agent.yaml",
                "./agent.yaml",
                "/etc/magi/agent.yaml",
            ]:
                if os.path.exists(default_path):
                    config_path = default_path
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
            if data.startswith("${") and data.endswith("}"):
                # 去掉 ${ 和 }
                var_spec = data[2:-1]

                # 检查是否有默认值
                if ":" in var_spec:
                    var_name, default_value = var_spec.split(":", 1)
                    return os.getenv(var_name, default_value)
                else:
                    return os.getenv(var_spec)
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
