"""将真机读取隔离到短命进程，避免 UIA/WinRT 卡住整个探测。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


PROCESS_NAMES = {"kugou.exe", "kugoumusic.exe"}


def require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("需要在运行酷狗的 Windows 用户桌面会话中执行")


def processes() -> list[dict[str, Any]]:
    """只返回酷狗主进程；无权读取的其他系统进程直接跳过。"""
    require_windows()
    import win32api
    import win32process
    import ctypes
    from ctypes import wintypes

    query_path = ctypes.WinDLL("kernel32", use_last_error=True).QueryFullProcessImageNameW
    query_path.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                           ctypes.POINTER(wintypes.DWORD)]
    query_path.restype = wintypes.BOOL

    result = []
    for pid in win32process.EnumProcesses():
        handle = None
        try:
            handle = win32api.OpenProcess(0x1000, False, pid)
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not query_path(int(handle), 0, buffer, ctypes.byref(size)):
                continue
            path = buffer.value
            if Path(path).name.casefold() in PROCESS_NAMES:
                result.append({"pid": pid, "exe": path})
        except (OSError, win32api.error):
            continue
        finally:
            if handle is not None:
                handle.Close()
    return sorted(result, key=lambda item: item["pid"])


def windows(running: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """枚举进程所属的顶层窗口，不激活窗口、不读其他应用的标题。"""
    import win32gui
    import win32process

    pids = {item["pid"] for item in running}
    result = []

    def visit(hwnd: int, _: Any) -> None:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in pids:
            result.append({
                "hwnd": hwnd, "pid": pid,
                "title": win32gui.GetWindowText(hwnd),
                "class_name": win32gui.GetClassName(hwnd),
                "visible": bool(win32gui.IsWindowVisible(hwnd)),
                "minimized": bool(win32gui.IsIconic(hwnd)),
                "rect": list(win32gui.GetWindowRect(hwnd)),
            })

    win32gui.EnumWindows(visit, None)
    return result


def version_string(ms: int, ls: int) -> str:
    return ".".join(str(value) for value in (ms >> 16, ms & 65535, ls >> 16, ls & 65535))


def file_version(path: str) -> dict[str, str]:
    import win32api

    info = win32api.GetFileVersionInfo(path, "\\")
    return {
        "file_version": version_string(info["FileVersionMS"], info["FileVersionLS"]),
        "product_version": version_string(info["ProductVersionMS"], info["ProductVersionLS"]),
    }


def envelope(probe: str, status: str, **values: Any) -> dict[str, Any]:
    return {"probe": probe, "observed_at": datetime.now().astimezone().isoformat(),
            "status": status, **values}


def isolated(script: str, args: list[str], timeout: float) -> dict[str, Any]:
    try:
        child = subprocess.run(
            [sys.executable, "-X", "utf8", script, *args, "--_worker"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return envelope(Path(script).stem, "timeout", timeout_seconds=timeout,
                        error="探测超时，子进程已终止；这不代表酷狗支持或不支持该能力")
    try:
        result = json.loads(child.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            raise ValueError("invalid envelope")
        if child.returncode and result["status"] == "ok":
            raise ValueError("worker exited with failure")
        return result
    except (ValueError, TypeError):
        return envelope(Path(script).stem, "error", error="探测进程没有返回有效 JSON",
                        diagnostic=child.stderr[-2000:])


def emit(result: dict[str, Any], output: str | None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n", encoding="utf-8")
    print(content)


def cli(probe: str, read: Callable[[argparse.Namespace], dict[str, Any]],
        configure: Callable[[argparse.ArgumentParser], None] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=15, help="子进程总时限，秒")
    parser.add_argument("--output", help="另存 JSON（可能包含当前曲目/控件文字，请自行保管）")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    if configure:
        configure(parser)
    args = parser.parse_args()
    if not 0 < args.timeout <= 120:
        parser.error("timeout 需要在 0 到 120 秒之间")
    if args._worker:
        try:
            require_windows()
            result = envelope(probe, "ok", data=read(args))
        except ImportError as exc:
            result = envelope(probe, "dependency_missing", error=str(exc),
                              hint="安装 probes/requirements.txt 后重试")
        except Exception as exc:
            result = envelope(probe, "error", error=f"{type(exc).__name__}: {exc}")
        emit(result, None)
    else:
        result = isolated(str(Path(sys.argv[0]).resolve()), sys.argv[1:], args.timeout)
        emit(result, args.output)
    if result["status"] != "ok":
        raise SystemExit(2)
