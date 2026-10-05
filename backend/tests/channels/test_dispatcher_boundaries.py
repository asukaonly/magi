import ast
from pathlib import Path


def _api_imports(source: str) -> list[str]:
    from importlib.util import resolve_name

    found = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, "magi.channels")
            names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
        found.extend(name for name in names if name == "magi.api" or name.startswith("magi.api."))
    return found


def test_channel_dispatcher_has_no_api_import_in_any_static_import_form():
    from textwrap import dedent

    source = (Path(__file__).parents[2] / "src" / "magi" / "channels" / "dispatcher.py").read_text()
    assert _api_imports(source) == []
    for statement in (
        "import magi.api",
        "import magi.api.chat as transport",
        "from magi import api",
        "from magi.api import chat",
        "from .. import api",
        "from ..api import chat",
        "def deferred():\n    from ..api.chat import dispatch",
    ):
        assert _api_imports(source + "\n" + dedent(statement)), statement
    assert (
        _api_imports("from ..chat import dispatch\nfrom . import api\nimport magi.api_client") == []
    )
