"""Resumable cutover between logical storage owners under an offline lease."""

from __future__ import annotations

from magi_plugin_sdk.storage_digest import snapshot_digest

from typing import Any, Protocol, TypeVar

from .storage_bindings import StorageBindingFile, StorageTarget, StorageTransferIntent

class LogicalSnapshot(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, Any]: ...
    def is_empty(self) -> bool: ...


State = TypeVar("State", bound=LogicalSnapshot)


class LogicalStateTransfer(Protocol[State]):
    async def export_state(self) -> State: ...
    async def import_state(self, snapshot: State, *, replace: bool = False) -> None: ...




async def cutover_logical_state(
    *,
    binding_file: StorageBindingFile,
    destination: StorageTarget,
    reader: LogicalStateTransfer[State],
    writer: LogicalStateTransfer[State],
    replace_destination: bool = False,
) -> dict[str, str]:
    """Persist intent before import; activate only after an exact logical verification."""
    binding = binding_file.read_or_create()
    snapshot = await reader.export_state()
    digest = snapshot_digest(snapshot)
    intent = StorageTransferIntent(
        destination=destination, snapshot_digest=digest, replace_destination=replace_destination
    )
    if binding.pending is not None and binding.pending != intent:
        raise RuntimeError(
            "Resume the original storage transfer before requesting a different cutover"
        )
    target = await writer.export_state()
    if snapshot_digest(target) != digest and not target.is_empty() and not replace_destination:
        raise ValueError(
            "Destination has data; explicitly replace it or choose an empty destination"
        )
    binding.pending = intent
    binding_file.write(binding)
    if snapshot_digest(target) != digest:
        await writer.import_state(snapshot, replace=replace_destination)
    if snapshot_digest(await writer.export_state()) != digest:
        raise RuntimeError("Storage verification failed; source remains active")
    binding.active = destination
    binding.pending = None
    binding_file.write(binding)
    return {"status": "migrated", "storage": destination.kind}
