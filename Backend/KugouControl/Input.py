"""向酷狗窗口投递鼠标、键盘消息。

消息直接进酷狗自己的消息队列：不移动真实鼠标，不切换前台窗口，
PPT 正在放映、酷狗被别的窗口盖住时也能用。窗口最小化或在托盘时无效，调用前先检查。
"""

from __future__ import annotations

import win32api
import win32con
import win32gui


def click(hwnd: int, x: float, y: float, *, double: bool = False) -> None:
    """x、y 是屏幕坐标（和 UIA 矩形同一坐标系）。"""

    client_x, client_y = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
    point = win32api.MAKELONG(client_x, client_y)
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, point)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, point)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, point)
    if double:
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON, point)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, point)


def press(hwnd: int, key: int, times: int = 1) -> None:
    for _ in range(times):
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, key, 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, key, 0xC0000001)


def type_text(hwnd: int, text: str) -> None:
    """逐个 UTF-16 码元投递，中文也按原样进输入框，不经过输入法。"""

    data = text.encode("utf-16-le")
    for index in range(0, len(data), 2):
        win32gui.PostMessage(hwnd, win32con.WM_CHAR, int.from_bytes(data[index:index + 2], "little"), 0)


def capture(hwnd: int, top: float, bottom: float) -> bytes:
    """窗口里一条横带（屏幕纵坐标 top 到 bottom）当前画面的指纹，用来判断画面变没变。窗口被盖住也能取到。"""

    import ctypes
    import hashlib
    import win32ui

    left, window_top, right, window_bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, window_bottom - window_top
    window_dc = win32gui.GetWindowDC(hwnd)
    source = win32ui.CreateDCFromHandle(window_dc)
    memory = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(source, width, height)
        memory.SelectObject(bitmap)
        ctypes.windll.user32.PrintWindow(hwnd, memory.GetSafeHdc(), 2)
        rows = bitmap.GetBitmapBits(True)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory.DeleteDC()
        source.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
    stride = len(rows) // max(height, 1)
    first, last = (min(max(int(y) - window_top, 0), height) for y in (top, bottom))
    return hashlib.md5(rows[first * stride:last * stride]).digest()
