"""Memory API test doubles with an explicit request-operation boundary."""

from types import SimpleNamespace

from magi.core.operation_barrier import AsyncOperationBarrier


class MemoryApiStub(SimpleNamespace):
    """Expose only configured services and use the real shared-operation guard."""

    def __init__(self, **services):
        super().__init__(
            **{
                "l0": None,
                "l1": None,
                "l2": None,
                "l3": None,
                "l4": None,
                "l2_entity_catalog": None,
                "memory_operation_guard": AsyncOperationBarrier().operation,
                **services,
            }
        )
