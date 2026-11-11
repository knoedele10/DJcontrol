"""保持一个 COM 工作进程，减少重复启动；超时只销毁隔离进程，不重发命令。"""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)


class WorkerProcess:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.responses: queue.Queue = queue.Queue()

    def __call__(self, args: list[str], *, cwd: str, timeout: float, **kwargs) -> subprocess.CompletedProcess:
        fresh = self.process is None or self.process.poll() is not None
        if fresh:
            self.close()
            self.responses = queue.Queue()
            self.process = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-m", "KugouControl.Worker", "--serve"],
                cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            process, responses = self.process, self.responses

            def output() -> None:
                try:
                    for line in process.stdout:
                        responses.put(line)
                finally:
                    process.stdout.close()
                    responses.put(None)

            def errors() -> None:
                try:
                    for line in process.stderr:
                        logger.warning("酷狗工作进程：%s", line.rstrip())
                finally:
                    process.stderr.close()

            threading.Thread(target=output, daemon=True).start()
            threading.Thread(target=errors, daemon=True).start()
        try:
            self.process.stdin.write(args[-1] + "\n")
            self.process.stdin.flush()
            line = self.responses.get(timeout=timeout + (4 if fresh else 0))
            if line is None:
                raise OSError("酷狗工作进程已经退出")
            return subprocess.CompletedProcess(args, 0, line, "")
        except queue.Empty as exc:
            self.close()
            raise subprocess.TimeoutExpired(args, timeout) from exc
        except (OSError, ValueError):
            self.close()
            raise

    def close(self) -> None:
        if self.process is not None:
            process, self.process = self.process, None
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            # reader 线程在 EOF 后退出；不要跨线程关闭它正在读取的管道。
            if process.stdin:
                process.stdin.close()
