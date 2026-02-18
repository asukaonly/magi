"""
Provider Base Classes

Abstract base classes for implementing service providers.
Each provider encapsulates the logic for a specific service backend.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Base provider configuration."""

    api_key: Optional[str] = Field(default=None, description="API key for authentication")
    base_url: Optional[str] = Field(default=None, description="Custom API endpoint URL")

    class Config:
        extra = "allow"  # Allow provider-specific config fields


class Provider(ABC):
    """
    Abstract base class for service providers.

    Each provider encapsulates the logic for a specific service backend.
    Providers are responsible for:
    - Managing their own configuration
    - Executing API calls
    - Normalizing results to a common format
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Provider identifier.

        This is used as the key in configuration and provider selection.
        Should be lowercase and URL-safe (e.g., 'brave', 'qweather').
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable provider name.

        Used for display in UI and logs (e.g., 'Brave Search', 'QWeather').
        """
        pass

    @abstractmethod
    def is_ready(self, config: ProviderConfig) -> bool:
        """
        Check if the provider is properly configured and ready to use.

        Args:
            config: Provider configuration

        Returns:
            True if the provider has all required configuration (e.g., API key)
        """
        pass

    @abstractmethod
    async def execute(
        self,
        params: Dict[str, Any],
        config: ProviderConfig
    ) -> Dict[str, Any]:
        """
        Execute the provider's API call.

        Args:
            params: Request parameters from the tool
            config: Provider configuration

        Returns:
            Normalized result dictionary

        Raises:
            Exception: If the API call fails
        """
        pass

    def get_config_schema(self) -> Dict[str, Any]:
        """
        Return JSON schema for provider-specific configuration.

        Override this method to add provider-specific config fields.

        Returns:
            Dictionary describing the configuration schema
        """
        return {
            "api_key": {
                "type": "string",
                "description": "API key for authentication",
                "required": True,
            },
            "base_url": {
                "type": "string",
                "description": "Custom API endpoint URL (optional)",
                "required": False,
            },
        }

    def get_default_config(self) -> ProviderConfig:
        """
        Get default configuration for this provider.

        Override this method to set provider-specific defaults.

        Returns:
            Default ProviderConfig instance
        """
        return ProviderConfig()
