"""Driver-independent persistence failures exposed by repository ports."""


class PersistenceUnavailableError(RuntimeError):
    """Storage did not confirm the operation; callers must not assume rollback."""


class PersistenceConflictError(RuntimeError):
    """A database constraint rejected the proposed write."""
