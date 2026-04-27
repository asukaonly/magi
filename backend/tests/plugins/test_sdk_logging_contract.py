import logging

from magi.plugins import configure_basic_logging as backend_configure_basic_logging
from magi.plugins import get_logger as backend_get_logger
from magi_plugin_sdk import configure_basic_logging as sdk_configure_basic_logging
from magi_plugin_sdk import get_logger as sdk_get_logger
from magi_plugin_sdk.logging import configure_basic_logging as module_configure_basic_logging
from magi_plugin_sdk.logging import get_logger as module_get_logger


def test_sdk_logging_helpers_are_exported_from_root_package() -> None:
    assert sdk_get_logger is module_get_logger
    assert sdk_configure_basic_logging is module_configure_basic_logging
    assert backend_get_logger is module_get_logger
    assert backend_configure_basic_logging is module_configure_basic_logging


def test_sdk_get_logger_returns_stdlib_logger() -> None:
    logger = sdk_get_logger("plugins.example")

    assert isinstance(logger, logging.Logger)
    assert logger.name == "plugins.example"