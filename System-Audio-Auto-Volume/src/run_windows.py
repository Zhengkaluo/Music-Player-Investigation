"""Windows-only entry point for the read-only system audio monitor."""

import argparse
from pathlib import Path
import sys

from service import ROOT, serve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--settings", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port 必须在 1024..65535 之间")
    if sys.platform != "win32":
        parser.error("此入口只能在 Windows 运行")

    from windows_monitor import WindowsMonitor

    return serve(
        WindowsMonitor(),
        args.settings or ROOT / "runtime" / "windows-settings.json",
        args.port,
        "M4 Windows 真实只读监控：读取 WASAPI loopback 和 EndpointVolume，绝不写入音量。",
    )


if __name__ == "__main__":
    raise SystemExit(main())
