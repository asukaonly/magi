"""Plugin i18n helpers - re-exported from magi-plugin-sdk."""
from magi_plugin_sdk.i18n import (  # noqa: F401
    DEFAULT_LANGUAGE,
    LANGUAGE_ALIASES,
    PluginI18n,
    get_current_language,
    get_explicit_current_language,
    language_context,
    set_current_language,
)
from ..i18n import get_effective_language


def resolve_host_plugin_language() -> str:
    """Resolve the active language for plugin calls across host and subprocess boundaries."""
    explicit = get_explicit_current_language()
    if explicit:
        return explicit
    return get_effective_language(default=DEFAULT_LANGUAGE)

