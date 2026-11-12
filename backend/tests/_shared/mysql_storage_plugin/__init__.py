"""Optional native conformance imports from the companion plugin checkout."""
import os
from pathlib import Path
import pytest

package = Path(os.environ.get("MAGI_TEST_MYSQL_PLUGIN_ROOT", Path(__file__).resolve().parents[5] / "magi-plugins/plugins/storage-mysql"))
if not (package / "plugin.py").is_file():
    pytest.skip("Set MAGI_TEST_MYSQL_PLUGIN_ROOT to the storage-mysql package", allow_module_level=True)
__path__.append(str(package))
