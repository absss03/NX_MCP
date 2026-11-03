"""Run with external Python (e.g. double-click) to stop the blocking NX journal."""

import sys
from pathlib import Path

source_root = Path(__file__).resolve().parents[1] / "src"
if source_root.is_dir():
    sys.path.insert(0, str(source_root))

from nx_mcp.journal.launcher import load_settings  # noqa: E402


def main() -> None:
    settings = load_settings(Path(__file__).with_name("python-bridge.json"))
    settings.stop_file.parent.mkdir(parents=True, exist_ok=True)
    settings.stop_file.touch()
    print(f"NX MCP stop requested: {settings.stop_file}")


if __name__ == "__main__":
    main()
