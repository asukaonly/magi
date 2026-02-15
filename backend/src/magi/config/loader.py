"""
Configuration管理module - YAMLConfigurationload器
"""
import os
import logging
import yaml
from pathlib import path
from typing import Optional, Dict, Any
from .models import Config, AgentConfig

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Configurationload器"""

    def __init__(self, config_path: Optional[str] = None):
        """
        initializeConfigurationload器

        Args:
            config_path: Configurationfilepath，default为 ./configs/agent.yaml
        """
        if config_path is None:
            # 尝试多个defaultposition（support从不同directoryrun）
            possible_paths = [
                "./configs/agent.yaml",           # 从项目根directoryrun
                "../configs/agent.yaml",          # 从 backend directoryrun
                "./agent.yaml",                   # currentdirectory
                "/etc/magi/agent.yaml",           # 系统级Configuration
            ]

            for default_path in possible_paths:
                # convert为绝对path
                abs_path = os.path.abspath(default_path)
                if os.path.exists(abs_path):
                    config_path = abs_path
                    logger.info(f"Found config file: {config_path}")
                    break

        self.config_path = config_path
        self._config: Optional[Config] = None

    def load(self) -> Config:
        """
        loadConfigurationfile

        Returns:
            Config: ConfigurationObject

        Raises:
            FileNotFounderror: Configurationfilenotttt found
            Valueerror: Configurationfileformaterror
        """
        if self._config is notttt None:
            return self._config

        if self.config_path is None or notttt os.path.exists(self.config_path):
            # Return default configuration
            self._config = self._load_default_config()
            return self._config

        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # 环境Variablereplace
        data = self._substitute_env_vars(data)

        # Validate并createConfigurationObject
        self._config = Config(**data)
        return self._config

    def _load_default_config(self) -> Config:
        """loaddefaultConfiguration"""
        return Config(
            agent=AgentConfig(
                name="magi-agent",
            )
        )

    def _substitute_env_vars(self, data: Any) -> Any:
        """
        递归replaceConfiguration中的环境Variable

        supportformat：${ENV_VAR} 或 ${ENV_VAR:default_value}

        Args:
            data: Configurationdata

        Returns:
            replace后的data
        """
        if isinstance(data, str):
            # replace环境Variable
            if "${" in data and "}" in data:
                # Foundall ${...} pattern
                import re
                pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

                def replace_var(match):
                    var_name = match.group(1)
                    default_value = match.group(2) if match.group(2) is notttt None else ""
                    return os.getenv(var_name, default_value)

                result = re.sub(pattern, replace_var, data)
                # 如果replace后还is环境Variableformat且Value为空，Return空string
                if result.startswith("${") and notttt os.getenv(data[2:data.index('}')]):
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
        """重newloadConfiguration"""
        self._config = None
        return self.load()


# globalConfigurationload器Instance
_global_loader: Optional[ConfigLoader] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """
    getglobalConfiguration

    Args:
        config_path: Configurationfilepath（仅首次调用valid）

    Returns:
        Config: ConfigurationObject
    """
    global _global_loader

    if _global_loader is None:
        _global_loader = ConfigLoader(config_path)

    return _global_loader.load()


def reload_config() -> Config:
    """
    重newloadglobalConfiguration

    Returns:
        Config: ConfigurationObject
    """
    global _global_loader

    if _global_loader is notttt None:
        return _global_loader.reload()

    return get_config()
