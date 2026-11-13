"""桌面端后端启动器：运行 FastAPI 服务，并在父进程关闭标准输入时优雅退出。"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import uvicorn


def _resolve_backend_dir() -> Path:
    configured = os.environ.get("KGDASH_BACKEND_DIR")
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _watch_parent(server: uvicorn.Server) -> None:
    """Electron 退出或异常终止时标准输入管道会立即 EOF，据此触发 lifespan 清理。"""

    try:
        if sys.stdin is not None:
            for line in sys.stdin:
                if line.strip().lower() == "shutdown":
                    break
    except Exception:
        pass
    server.should_exit = True


def main() -> int:
    backend_dir = _resolve_backend_dir()
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    os.chdir(backend_dir)

    host = os.environ.get("KGDASH_HOST", "127.0.0.1")
    port = int(os.environ.get("KGDASH_PORT", "18081"))
    log_level = os.environ.get("KGDASH_LOG_LEVEL", "info").lower()

    config = uvicorn.Config(
        "Main:app",
        host=host,
        port=port,
        workers=1,
        log_level=log_level,
    )
    server = uvicorn.Server(config)
    if sys.stdin is not None and not sys.stdin.isatty():
        watcher = threading.Thread(
            target=_watch_parent,
            args=(server,),
            daemon=True,
            name="desktop-parent-watch",
        )
        watcher.start()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
