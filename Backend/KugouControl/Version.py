"""从主窗口确认进程和版本，不启动酷狗，不枚举其他应用的标题内容。"""

from __future__ import annotations

from pathlib import Path

from KugouControl.Profiles import MAIN_CLASS


def discover() -> dict:
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32gui
    import win32process

    query = ctypes.WinDLL("kernel32", use_last_error=True).QueryFullProcessImageNameW
    query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    found = []

    def visit(hwnd: int, _: object) -> None:
        if win32gui.GetClassName(hwnd) != MAIN_CLASS:
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if title == "桌面歌词 - 酷狗音乐":
            return
        if title != "酷狗音乐" and not title.endswith(" - 酷狗音乐"):
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        # 最小化的窗口尺寸只有标题栏那么大，不能按尺寸排除，否则会报成"找不到主窗口"而不是"已最小化"。
        if not win32gui.IsIconic(hwnd) and (right - left < 400 or bottom - top < 200):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = None
        try:
            handle = win32api.OpenProcess(0x1000, False, pid)
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not query(int(handle), 0, buf, ctypes.byref(size)):
                return
            if Path(buf.value).name.casefold() != "kugou.exe":
                return
            version = win32api.GetFileVersionInfo(buf.value, "\\")
            ms, ls = version["FileVersionMS"], version["FileVersionLS"]
            found.append({"hwnd": hwnd, "pid": pid, "exe": buf.value,
                          "version": f"{ms >> 16}.{ms & 65535}.{ls >> 16}.{ls & 65535}",
                          "window_title": title, "blocked": not bool(win32gui.IsWindowEnabled(hwnd)),
                          "minimized": bool(win32gui.IsIconic(hwnd) or not win32gui.IsWindowVisible(hwnd))})
        except (OSError, win32api.error):
            return
        finally:
            if handle is not None:
                handle.Close()

    win32gui.EnumWindows(visit, None)
    return found[0] if len(found) == 1 else {"error": "未找到唯一酷狗主窗口，请启动酷狗并关闭多余弹窗"}
