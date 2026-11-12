"""Inject selected plugin repositories before their domain consumers start."""

from magi_plugin_sdk.storage_dispatch import CHANNEL_REPOSITORY_CONTRACTS
from magi_plugin_sdk.storage_ports.events import EventStorageOperations
from ..channels.ports import ChannelRepositories
from ..outreach.ports import OutreachRepositories
from ..db.storage_proxy import RepositoryProxy
from .context import RuntimeBootstrapContext, require_initialized
from .chat_storage import ChatStorageRuntime, compose_chat_storage
from .lifecycle import LifecycleModule
from .storage_selection import OpenStorage, resolve_storage, preflight_storage, open_storage, binding_file


class StructuredStorageModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(name="runtime_structured_storage", dependencies=("runtime_configuration", "runtime_storage_plugins"))
        self.context = context
        self.sessions: list[OpenStorage] = []
        self.chat: ChatStorageRuntime | None = None

    async def init(self) -> None:
        config = require_initialized(self.context.core.config, "configuration")
        paths = require_initialized(self.context.core.runtime_paths, "runtime paths")
        runtime = require_initialized(self.context.plugins.storage_runtime, "storage plugins")
        selected = {}
        try:
            # Validate all bindings before any provider migrates its schema.
            for domain in ("channels", "memory_events", "chat"):
                entry, target = await resolve_storage(runtime, getattr(config.structured_storage, domain), domain)
                binding = await preflight_storage(paths, runtime, domain, entry, target)
                selected[domain] = (entry, target, binding)
            opened = {}
            for domain, (entry, target, binding) in selected.items():
                session = await open_storage(entry, target, domain, binding.center_id, migrate=True)
                self.sessions.append(session)
                runtime.registry.pin(entry.connection_id)
                opened[domain] = session
            channel = opened["channels"]
            repositories = {name: RepositoryProxy(channel.entry.provider, channel.opened.session_id, name, contract)
                            for name, contract in CHANNEL_REPOSITORY_CONTRACTS.items()}
            self.context.channels.repositories = ChannelRepositories(repositories["sessions"], repositories["receipts"], repositories["binding_settings"])
            self.context.outreach.repositories = OutreachRepositories(repositories["outbox"], repositories["delivery_log"])
            events = opened["memory_events"]
            self.context.memory.event_repository = RepositoryProxy(events.entry.provider, events.opened.session_id, "events", EventStorageOperations)
            self.context.memory.event_state_transfer = events.transfer
            self.chat = compose_chat_storage(paths, opened["chat"])
            await self.chat.store.initialize()
            await self.context.memory.event_repository.initialize()
            await self.chat.reader.aget_interrupted_global_clear_count()
            self.context.chat.store = self.chat.store
            self.context.chat.reader = self.chat.reader
            self.context.chat.state_transfer = self.chat.state_transfer
            for domain, (_, target, binding) in selected.items():
                binding.active = target
                binding_file(paths, domain).write(binding)
        except BaseException:
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        self.context.channels.repositories = None
        self.context.outreach.repositories = None
        self.context.memory.event_repository = None
        self.context.memory.event_state_transfer = None
        self.context.chat.store = None
        self.context.chat.reader = None
        self.context.chat.state_transfer = None
        failures = []
        if self.chat is not None:
            try:
                await self.chat.close()
            except BaseException as exc:
                failures.append(exc)
            self.chat = None
        for session in reversed(self.sessions):
            try:
                await session.close()
            except BaseException as exc:
                failures.append(exc)
        self.sessions.clear()
        if failures:
            raise failures[0]
