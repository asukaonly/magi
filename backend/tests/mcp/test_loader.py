from pathlib import Path
import pytest
from magi.mcp.loader import MCPConfigLoader

def write(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)

def test_loads_all_files(tmp_path: Path):
    write(tmp_path / "github.toml", """
[server]
id = "github"
name = "GitHub"
[transport]
kind = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
""")
    write(tmp_path / "fs.toml", """
[server]
id = "fs"
name = "FS"
enabled = false
[transport]
kind = "stdio"
command = "uvx"
""")
    loader = MCPConfigLoader(tmp_path)
    cfgs = loader.load_all()
    assert {c.server.id for c in cfgs} == {"github", "fs"}

def test_id_must_match_filename(tmp_path: Path):
    write(tmp_path / "wrong.toml", """
[server]
id = "different"
name = "x"
[transport]
kind = "stdio"
command = "x"
""")
    loader = MCPConfigLoader(tmp_path)
    with pytest.raises(ValueError, match="filename"):
        loader.load_all()

def test_env_expansion(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MAGI_TEST_TOKEN", "secret123")
    write(tmp_path / "github.toml", """
[server]
id = "github"
name = "x"
[transport]
kind = "stdio"
command = "npx"
[transport.env]
GITHUB_TOKEN = "${env:MAGI_TEST_TOKEN}"
""")
    loader = MCPConfigLoader(tmp_path)
    [cfg] = loader.load_all()
    assert cfg.transport.env["GITHUB_TOKEN"] == "secret123"

def test_env_expansion_missing_var(tmp_path: Path):
    write(tmp_path / "x.toml", """
[server]
id = "x"
name = "x"
[transport]
kind = "stdio"
command = "npx"
[transport.env]
TOKEN = "${env:DEFINITELY_NOT_SET_XYZ}"
""")
    loader = MCPConfigLoader(tmp_path)
    [cfg] = loader.load_all()
    assert cfg.transport.env["TOKEN"] == ""

def test_missing_directory_returns_empty(tmp_path: Path):
    loader = MCPConfigLoader(tmp_path / "does-not-exist")
    assert loader.load_all() == []

def test_index_toml_skipped(tmp_path: Path):
    # index.toml should not be parsed as a server config
    write(tmp_path / "index.toml", "# index file managed by magi\n")
    write(tmp_path / "x.toml", """
[server]
id = "x"
name = "x"
[transport]
kind = "stdio"
command = "x"
""")
    loader = MCPConfigLoader(tmp_path)
    [cfg] = loader.load_all()
    assert cfg.server.id == "x"
