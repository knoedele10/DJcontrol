"""读取运行中的酷狗版本；未启动时可显式指定安装文件，只读。"""

import argparse
from pathlib import Path
from typing import Any

from KugouCommon import cli, file_version, processes


def read(args: argparse.Namespace) -> dict[str, Any]:
    running = processes()
    installed = None
    if args.exe:
        path = str(Path(args.exe).resolve(strict=True))
        installed = {"exe": path, **file_version(path)}
    return {"running": bool(running),
            "processes": [{**item, **file_version(item["exe"])} for item in running],
            "explicit_file": installed}


if __name__ == "__main__":
    cli("KugouVersion", read, lambda parser: parser.add_argument("--exe"))
