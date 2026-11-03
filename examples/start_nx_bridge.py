"""Run this file as a Python journal inside Siemens NX to start the bridge."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

source_root = Path(__file__).resolve().parents[1] / "src"
if source_root.is_dir():
    sys.path.insert(0, str(source_root))

from nx_mcp.journal.launcher import load_settings  # noqa: E402
from nx_mcp.nx_bridge import pump_bridge, start_bridge, stop_bridge  # noqa: E402


def main() -> None:
    # NX captures a journal's stdout, so the bridge's own startup diagnostics
    # (a stale descriptor it ignored, for one) land in the session log.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(Path(__file__).with_name("python-bridge.json"))
    settings.workspace.mkdir(parents=True, exist_ok=True)
    # Playing this journal explicitly selects the blocking Python bridge.
    # NXOpen calls remain on this journal's thread, just as with run_journal.exe.
    descriptor = start_bridge(
        settings.workspace,
        descriptor_path=settings.state_dir / "bridge.json",
        allow_unverified_threading=True,
    )
    try:
        settings.stop_file.unlink(missing_ok=True)
        message = (
            f"NX MCP Python bridge: {descriptor.host}:{descriptor.port} ({descriptor.nx_version})\n"
            f"NX_MCP_WORKSPACE: {settings.workspace}\n"
            f"NX_MCP_STATE_DIR: {settings.state_dir}\n"
            f"Stop file: {settings.stop_file}\n"
            "NX stays occupied while this journal runs.\n"
            "To stop, run examples/stop_nx_bridge.py outside NX, or create the stop file."
        )
        print(message)
        import NXOpen

        listing = NXOpen.Session.GetSession().ListingWindow
        listing.Open()
        listing.WriteLine(message)
        while not settings.stop_file.exists():
            pump_bridge(timeout=0.1)
    finally:
        stop_bridge()


if __name__ == "__main__":
    main()
