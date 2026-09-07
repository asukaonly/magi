"""Real workers apply the protocol-2 minimum SDK contract before plugin import."""

import pytest

from magi.plugins.process_runtime import ProcessPluginProxy, PluginProcessError
from test_process_runtime import plugin_setup  # noqa: F401


@pytest.mark.parametrize("minimum", ["0.1.0", "0.2.0"])
def test_worker_accepts_satisfied_minimum(plugin_setup, minimum):
    manifest, connection, context = plugin_setup
    proxy = ProcessPluginProxy(
        manifest.model_copy(update={"min_sdk_version": minimum}), connection, context
    )
    try:
        assert proxy.diagnostics["healthy"]
    finally:
        proxy._terminate()


def test_worker_rejects_future_sdk_before_import(plugin_setup):
    manifest, connection, context = plugin_setup
    with pytest.raises(PluginProcessError, match="requires SDK"):
        ProcessPluginProxy(
            manifest.model_copy(update={"min_sdk_version": "9.0.0"}), connection, context
        )
    assert context.credentials.get("boot") is None
