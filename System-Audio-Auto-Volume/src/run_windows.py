"""Windows entry point for monitoring and explicit M6 manual volume tests."""

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
        WindowsMonitor(curve_path=ROOT / "runtime" / "windows-volume-curve.json"),
        args.settings or ROOT / "runtime" / "windows-settings.json",
        args.port,
        "Windows：默认只监控/影子；已校准设备可手动开启自动压低或自动调节（回升不超过开启时的音量，退出时安全恢复）。",
    )


if __name__ == "__main__":
    raise SystemExit(main())
