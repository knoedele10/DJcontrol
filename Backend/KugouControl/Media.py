"""只发送版本档案中的媒体键一次，不自动重试。"""

from KugouControl.Profiles import MEDIA_KEYS
import subprocess
import sys


def send(action: str) -> None:
    if action not in MEDIA_KEYS:
        raise ValueError("未知媒体命令")
    # 输入进程不持有 UIA COM 客户端，避免输入与控件读取互相等待。
    subprocess.run([sys.executable, "-m", "KugouControl.Media", action],
                   check=True, timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _send_native(action: str) -> None:
    import win32api
    import win32con

    code = MEDIA_KEYS[action]
    try:
        win32api.keybd_event(code, 0, 0, 0)
    finally:
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)


if __name__ == "__main__":
    _send_native(sys.argv[1])
