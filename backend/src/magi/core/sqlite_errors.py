"""Translate SQLite failures at repository operation boundaries."""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import wraps
import sqlite3
from typing import ParamSpec, TypeVar

from .persistence_errors import PersistenceConflictError, PersistenceUnavailableError

_Args = ParamSpec("_Args")
_Result = TypeVar("_Result")


@contextmanager
def sqlite_storage_errors() -> Iterator[None]:
    try:
        yield
    except sqlite3.IntegrityError as exc:
        raise PersistenceConflictError("Storage constraint rejected the operation") from exc
    except sqlite3.Error as exc:
        raise PersistenceUnavailableError("Storage operation could not be confirmed") from exc


def sqlite_async_boundary(
    operation: Callable[_Args, Awaitable[_Result]],
) -> Callable[_Args, Awaitable[_Result]]:
    """Translate only driver failures, after the operation's cleanup has settled."""
    @wraps(operation)
    async def wrapped(*args: _Args.args, **kwargs: _Args.kwargs) -> _Result:
        with sqlite_storage_errors():
            return await operation(*args, **kwargs)
    return wrapped
