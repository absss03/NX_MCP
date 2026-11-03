"""Configuration shared by the Python start journal and external stop script."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JournalSettings:
    workspace: Path
    state_dir: Path
    stop_file: Path


def load_settings(config_file: Path) -> JournalSettings:
    config = json.loads(config_file.read_text(encoding="utf-8-sig")) if config_file.exists() else {}
    if not isinstance(config, dict):
        raise ValueError(f"{config_file} must contain a JSON object")

    def path(key: str, environment: str, default: Path) -> Path:
        value = os.environ.get(environment) or config.get(key) or str(default)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"{key} must be an absolute path: {value!r}")
        return Path(value)

    workspace = path("workspace", "NX_MCP_WORKSPACE", Path.home() / "NX_MCP_WORKSPACE")
    state = path("state_dir", "NX_MCP_STATE_DIR", Path.home() / ".nx-mcp")
    stop = path("stop_file", "NX_MCP_BRIDGE_STOP_FILE", state / "python-bridge.stop")
    return JournalSettings(workspace, state, stop)
