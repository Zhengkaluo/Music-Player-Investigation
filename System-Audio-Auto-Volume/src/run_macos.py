"""macOS entry point for monitoring and explicit M6 manual volume tests."""

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
    if sys.platform != "darwin":
        parser.error("此入口只能在 macOS 运行")

    from macos_monitor import MacOSMonitor

    return serve(
        MacOSMonitor(),
        args.settings or ROOT / "runtime" / "macos-settings.json",
        args.port,
        "M8a macOS：真实影子建议不执行；只有界面人工测试按钮可以小幅写入并安全恢复音量。",
    )


if __name__ == "__main__":
    raise SystemExit(main())
