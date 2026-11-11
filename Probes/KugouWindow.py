"""保留不同播放状态下的窗口标题原文，不把手工标签当成实际状态。"""

import argparse
from typing import Any

from KugouCommon import cli, processes, windows


def read(args: argparse.Namespace) -> dict[str, Any]:
    running = processes()
    return {"running": bool(running), "declared_label": args.label,
            "label_verified": False, "windows": windows(running)}


if __name__ == "__main__":
    cli("KugouWindow", read, lambda parser: parser.add_argument(
        "--label", choices=["playing", "paused", "idle", "unknown"], default="unknown"))
