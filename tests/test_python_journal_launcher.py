"""Python journal configuration and lifecycle without a running NX session."""

import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nx_mcp import nx_bridge
from nx_mcp.journal.launcher import load_settings

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.fake_nx


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("NX_MCP_WORKSPACE", "NX_MCP_STATE_DIR", "NX_MCP_BRIDGE_STOP_FILE"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_need_no_console_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings = load_settings(tmp_path / "absent.json")
    assert settings.workspace == tmp_path / "NX_MCP_WORKSPACE"
    assert settings.state_dir == tmp_path / ".nx-mcp"
    assert settings.stop_file == settings.state_dir / "python-bridge.stop"


def test_config_and_environment_precedence(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"workspace": str(tmp_path / "parts"), "state_dir": str(tmp_path)})
    )
    assert load_settings(config).workspace == tmp_path / "parts"
    monkeypatch.setenv("NX_MCP_WORKSPACE", str(tmp_path / "override"))
    settings = load_settings(config)
    assert settings.workspace == tmp_path / "override"
    assert settings.stop_file == tmp_path / "python-bridge.stop"


@pytest.mark.parametrize("value", [[], {"workspace": "relative"}, {"state_dir": 123}])
def test_bad_config_rejected(tmp_path, value):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_settings(config)


@pytest.mark.parametrize("failure", [False, True])
def test_journal_pumps_and_always_stops(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("NX_MCP_WORKSPACE", str(tmp_path / "parts"))
    monkeypatch.setenv("NX_MCP_STATE_DIR", str(tmp_path))
    marker = tmp_path / "python-bridge.stop"
    marker.touch()  # Previous run's stop request must not end this run.
    start = Mock(return_value=SimpleNamespace(host="127.0.0.1", port=1, nx_version="fake"))
    stop = Mock()

    def pump(timeout):
        assert not marker.exists()
        assert timeout == 0.1
        if failure:
            raise RuntimeError("injected pump failure")
        # Exercise the external stop script: it needs no NXOpen calls.
        runpy.run_path(str(ROOT / "examples/stop_nx_bridge.py"), run_name="__main__")

    monkeypatch.setattr(nx_bridge, "start_bridge", start)
    monkeypatch.setattr(nx_bridge, "stop_bridge", stop)
    monkeypatch.setattr(nx_bridge, "pump_bridge", pump)
    listing = Mock()
    monkeypatch.setitem(
        sys.modules,
        "NXOpen",
        SimpleNamespace(
            Session=SimpleNamespace(GetSession=lambda: SimpleNamespace(ListingWindow=listing))
        ),
    )
    entry = runpy.run_path(str(ROOT / "examples/start_nx_bridge.py"))["main"]
    if failure:
        with pytest.raises(RuntimeError, match="injected pump failure"):
            entry()
    else:
        entry()
    start.assert_called_once_with(
        tmp_path / "parts",
        descriptor_path=tmp_path / "bridge.json",
        allow_unverified_threading=True,
    )
    stop.assert_called_once_with()
    listing.WriteLine.assert_called_once()
