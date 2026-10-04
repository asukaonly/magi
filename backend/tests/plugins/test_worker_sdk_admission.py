"""Real workers apply the protocol-2 minimum SDK contract before plugin import."""

import pytest

from magi.plugins.process_runtime import ProcessPluginProxy, PluginProcessError
from test_process_runtime import plugin_setup as plugin_setup


@pytest.mark.parametrize("minimum,accepted", [("0.1.0", True), ("0.2.0", True), ("9.0.0", False)])
def test_sdk_admission_precedes_plugin_module_execution(plugin_setup, tmp_path, minimum, accepted):
    from pathlib import Path

    manifest, connection, context = plugin_setup
    marker = tmp_path / "module-imported"
    module = Path(manifest.plugin_dir) / "plugin.py"
    module.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
        + module.read_text()
    )
    requested = manifest.model_copy(update={"min_sdk_version": minimum})
    if accepted:
        proxy = ProcessPluginProxy(requested, connection, context)
        try:
            assert proxy.diagnostics["healthy"]
            assert marker.read_text() == "imported"
            assert context.credentials.get("boot") == "worker-value"
        finally:
            proxy._terminate()
    else:
        with pytest.raises(PluginProcessError, match="requires SDK"):
            ProcessPluginProxy(requested, connection, context)
        assert not marker.exists()
        assert context.credentials.get("boot") is None
