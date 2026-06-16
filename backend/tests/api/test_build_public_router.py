"""Regression tests for _build_public_router across fastapi versions.

fastapi 0.137 changed include_router so nested routes appear as _IncludedRouter
wrappers (no .path) instead of flattened APIRoute objects. _build_public_router
must descend into them or every nested public route silently disappears.
"""
from fastapi import APIRouter

from magi.api.routes import _build_public_router, _iter_api_routes


def _child_with_send() -> APIRouter:
    child = APIRouter()

    @child.post("/send")
    def _send():  # pragma: no cover - schema-only
        return {}

    @child.get("/secret")
    def _secret():  # pragma: no cover - schema-only
        return {}

    return child


def test_iter_descends_into_included_router_wrapper():
    """Simulate fastapi>=0.137: an entry with no .path that exposes the child
    via `original_router`. The old isinstance(APIRoute) filter dropped these."""

    class _FakeIncludedRouter:  # mimics fastapi.routing._IncludedRouter
        def __init__(self, router: APIRouter) -> None:
            self.original_router = router

    parent = APIRouter()
    parent.routes.append(_FakeIncludedRouter(_child_with_send()))

    paths = {r.path for r in _iter_api_routes(parent)}
    assert "/send" in paths
    assert "/secret" in paths


def test_build_public_router_exposes_nested_routes_and_still_filters():
    """End-to-end on the installed fastapi: a real include_router'd child's
    allowlisted route is exposed; non-allowlisted ones stay excluded."""
    parent = APIRouter()
    parent.include_router(_child_with_send())

    public = _build_public_router(parent, {"/send": {"POST"}})
    paths = {r.path for r in public.routes}

    assert "/send" in paths          # nested route survives (the bug)
    assert "/secret" not in paths    # allowlist still filters
