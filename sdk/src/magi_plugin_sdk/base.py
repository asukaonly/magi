"""Unified plugin base class."""

from __future__ import annotations

from abc import ABC
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .channels import Channel
from .context import PluginContext
from .runtime import InvocationIdentity, OperationResult, OperationSpec, PluginConnection
from .contracts import (
    ExtractionProfileSpec,
    ExtensionFieldSpec,
    PluginManifest,
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    PluginSettingsResourceSpec,
    SummaryProfileSpec,
    TemporalSummaryFeatureBudget,
    TemporalSummarySourceFeatures,
)
from .ingress import PluginIngressHandlerRegistration
from .i18n import PluginI18n, get_current_language
from .sources import PluginRuntimePaths, SourceSpec
from .user_content import UserContentClearContext

if TYPE_CHECKING:
    from .history_imports import HistoryImporter, HistoryImporterSpec


class Plugin(ABC):
    """Base class for Magi plugin packages.

    Subclass this and implement one or more capability hooks to contribute
    tools, sources, channels, settings resources, ingress handlers, or
    temporal summary features to the Magi runtime.

    The runtime calls ``configure()`` before registration, so ``self.manifest``
    and ``self.settings`` are available inside all plugin methods.
    """

    def __init__(self) -> None:
        self.manifest: PluginManifest | None = None
        self.settings: dict[str, Any] = {}
        self.connection: PluginConnection | None = None
        self.context: PluginContext | None = None
        self._i18n: PluginI18n | None = None

    @property
    def plugin_id(self) -> str:
        """Return the plugin identifier from the manifest, or the class name."""
        return (
            self.manifest.plugin_id
            if self.manifest is not None
            else self.__class__.__name__
        )

    @property
    def plugin_dir(self) -> Path | None:
        """Resolve the plugin directory from the manifest or class file location."""
        if self.manifest and self.manifest.manifest_path:
            return Path(self.manifest.manifest_path).parent
        import inspect

        module = inspect.getmodule(self.__class__)
        if module and module.__file__:
            return Path(module.__file__).parent
        return None

    @property
    def i18n(self) -> PluginI18n:
        """Return the i18n helper for this plugin."""
        if self._i18n is None:
            plugin_dir = self.plugin_dir
            if plugin_dir is None:
                self._i18n = PluginI18n(self.plugin_id, Path("."))
            else:
                self._i18n = PluginI18n(self.plugin_id, plugin_dir)
        return self._i18n

    @property
    def connection_id(self) -> str:
        """Return the explicit instance identity after host configuration."""
        if self.connection is None:
            raise RuntimeError("Plugin connection has not been configured")
        return self.connection.connection_id

    def configure(
        self,
        *,
        manifest: PluginManifest,
        connection: PluginConnection,
        context: PluginContext,
    ) -> None:
        """Bind an explicit connection and its host-issued execution context.

        Each connection gets a separate plugin object. The host allocates paths
        and credentials before configuration; plugins must never choose their
        state root or infer a connection from package-level settings.
        """
        if manifest.plugin_id != connection.plugin_id:
            raise ValueError("Plugin manifest and connection identifiers do not match")
        if context.connection != connection:
            raise ValueError("Plugin context and connection bindings do not match")
        self.manifest = manifest
        self.connection = connection.model_copy(deep=True)
        self.context = context
        self.settings = deepcopy(connection.settings)
        self._i18n = None

    async def shutdown(self) -> None:
        """Release any long-lived resources owned by this plugin.

        Called by the host immediately before unloading the plugin (e.g. on
        disable, on settings update which triggers reload, on backend
        shutdown). Plugins that spawn subprocesses, run background timers,
        or hold OS observers MUST override this and tear them down here.

        Without this hook, host-driven reload (e.g. when the user updates
        settings via the UI) creates a fresh plugin instance alongside the
        old one — the old instance's timers keep ticking and its
        subprocess keeps consuming resources until the backend exits. The
        symptom is "I changed the interval to 120s and now captures fire
        every 3s" — actually four source instances at 12s each, stacking.

        Default is a no-op. Must be idempotent: the host may call shutdown
        multiple times. Should not raise; the host will log and continue
        if you do, but the next reload will still proceed.
        """

    async def clear_user_content(self, context: UserContentClearContext) -> None:
        """Erase plugin-owned local user content during a full product clear.

        Override this when the plugin retains collected content, derived
        content, buffered events, or unfinished user-content work outside the
        host stores. Keep the package, settings, credentials, connected-account
        state, and source-only cursors or watermarks. This hook must use local
        state only, perform no network I/O, and be idempotent because recovery
        may invoke the same generation again.

        The default is a safe no-op for stateless plugins.
        """
        _ = context

    def t(
        self,
        key: str,
        language: Optional[str] = None,
        fallback: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Look up a translated string for this plugin.

        Args:
            key: Translation key in dot-notation (e.g. ``"summary.played_track"``).
            language: Target language code; defaults to the current context language.
            fallback: String to return when the key is not found.
            **kwargs: Variables substituted into the translated string.

        Returns:
            Translated and interpolated string, or *key* if no translation found.
        """
        effective_language = language or get_current_language()
        return self.i18n.t(
            key, language=effective_language, fallback=fallback, **kwargs
        )

    def get_tools(self) -> list[type[Any]]:
        """Return tool classes contributed by this plugin."""
        return []

    def get_operations(self) -> list[OperationSpec]:
        """Declare business operations independently of the invoking UI."""
        return []

    async def invoke_operation(
        self, operation_id: str, arguments: dict[str, Any], identity: InvocationIdentity,
    ) -> OperationResult:
        """Execute one declared operation using a host-issued invocation identity."""
        raise KeyError(operation_id)

    def get_providers(self) -> list[tuple[str, str, Any]]:
        """Return (kind, provider_id, implementation) provider registrations.

        Supported kinds are web_search, model and external_agent.
        """
        return []

    def get_sources(self) -> list[tuple[str, Any, SourceSpec]]:
        """Return ``(source_id, source_instance, SourceSpec)`` tuples."""
        return []

    def get_history_importers(
        self,
    ) -> list[tuple[str, "HistoryImporter", "HistoryImporterSpec"]]:
        """Return ``(importer_id, importer, HistoryImporterSpec)`` tuples."""
        return []

    def get_channel(self) -> Channel | None:
        """Return an optional channel adapter instance contributed by this plugin."""
        return None

    def get_channel_fields(self) -> list[ExtensionFieldSpec]:
        """Return declarative settings fields for the optional channel contribution."""
        return []

    def get_hooks(self) -> list[tuple[str, Any, str | None]]:
        """Return ``(event_type, handler, matcher)`` tuples contributed by this plugin.

        ``event_type`` must be a valid ``HookEventType`` value (the string form, e.g.
        ``"PreToolUse"``). ``handler`` is an ``async def handler(ctx) -> HookDecision``.
        ``matcher`` is an optional substring used to filter the dispatch matcher key
        (e.g. ``"Bash"`` to only run on the Bash tool); pass ``None`` to receive
        every dispatch.

        Plugins that do not contribute hooks should leave the default empty list.
        """
        return []

    def get_skills(self) -> list[tuple[str, Path]]:
        """Return ``(skill_id, path_to_skill_dir)`` tuples contributed by this plugin.

        Each path must point at a directory containing a ``SKILL.md`` file. The host
        runtime is responsible for invoking the indexer on the returned paths.

        Plugins that do not contribute skills should leave the default empty list.
        """
        return []

    def get_settings_resources(self) -> list[PluginSettingsResourceSpec]:
        """Return read-only resource descriptors consumed by dynamic settings UI."""
        return []

    def read_settings_resource(self, resource_name: str) -> Any:
        """Resolve a named settings resource.

        Plugins that do not expose settings resources should keep the default
        implementation, which raises ``KeyError``.
        """
        raise KeyError(resource_name)

    def get_settings_actions(self) -> list[PluginSettingsActionSpec]:
        """Return host-rendered actions available from plugin settings surfaces."""
        return []

    async def start_settings_action(
        self,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionResult | dict[str, Any]:
        """Start a plugin-owned settings action session.

        Long-running actions may return ``status='pending'`` and keep
        provider-specific session state internally for later polling.
        """
        _ = session_id, field_values
        raise KeyError(action_id)

    async def poll_settings_action(
        self,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionResult | dict[str, Any]:
        """Poll a previously started plugin-owned settings action session."""
        _ = session_id, field_values
        raise KeyError(action_id)

    async def cancel_settings_action(
        self,
        action_id: str,
        *,
        session_id: str,
    ) -> PluginSettingsActionResult | dict[str, Any]:
        """Cancel a previously started plugin-owned settings action session."""
        _ = session_id
        raise KeyError(action_id)

    def build_temporal_summary_features(
        self,
        *,
        source_type: str,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
        budget: TemporalSummaryFeatureBudget | None = None,
    ) -> TemporalSummarySourceFeatures | dict[str, object] | None:
        """Return optional source-specific features for L3 temporal summaries.

        The host owns final cross-source L3 generation. Plugins should use this
        hook to expose compact source-local evidence, such as top entities,
        time buckets, coverage counts, and representative event ids.
        """
        _ = source_type, events, summary_category, period_start, period_end, budget
        return None

    def get_summary_profiles(self) -> list[SummaryProfileSpec]:
        """Return L3 activity summary profiles contributed by this plugin.

        Each profile declares a stable summary category, the sources
        that populate it, the time windows the host should schedule, and the
        intent verbs that route activity-summary queries to the category.
        """
        return []

    def get_extraction_profiles(self) -> list[ExtractionProfileSpec]:
        """Return L2 extraction profiles contributed by this plugin.

        The host validates all declared entity types, predicates, assertion
        families, and prompt instructions before using these profiles.
        """
        return []

    def get_plugin_ingress_registrations(
        self,
        *,
        runtime_paths: PluginRuntimePaths,
    ) -> list[PluginIngressHandlerRegistration]:
        """Return static ingress registrations for host-produced events."""
        _ = runtime_paths
        return []
