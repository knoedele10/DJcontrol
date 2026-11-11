"""人工核验按键链路；默认只展示方案，实际发送前每次确认。"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from KugouCommon import emit, envelope, processes, require_windows


MEDIA_KEYS = {"toggle": 0xB3, "next": 0xB0, "previous": 0xB1,
              "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}
MODIFIERS = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}
NAVIGATION_KEYS = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
WARNING = "将改变播放状态/歌曲/音量，系统媒体键也可能被其他播放器接收。请先确认现场允许出声。"


def hotkey_codes(text: str) -> list[int]:
    parts = text.casefold().split("+")
    if len(parts) < 2 or len(set(parts)) != len(parts):
        raise ValueError("热键需为 ctrl/alt/shift + 字母、数字、方向键或 F1–F12")
    if any(part not in MODIFIERS for part in parts[:-1]):
        raise ValueError("仅允许 ctrl/alt/shift 修饰键")
    if not ({"ctrl", "alt"} & set(parts[:-1])):
        raise ValueError("热键需包含 ctrl 或 alt，避免普通输入")
    key = parts[-1]
    if key == "f4" and "alt" in parts[:-1]:
        raise ValueError("Alt+F4 会关闭窗口，不允许作为媒体探测热键")
    if len(key) == 1 and key.isascii() and key.isalnum():
        code = ord(key.upper())
    elif key in NAVIGATION_KEYS:
        code = NAVIGATION_KEYS[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("末键仅允许字母、数字、方向键或 F1–F12")
    return [MODIFIERS[part] for part in parts[:-1]] + [code]


def confirm(prompt: Callable[[str], str] = input) -> bool:
    try:
        return prompt("输入 执行 才发送一次按键，其他输入取消：").strip() == "执行"
    except (EOFError, KeyboardInterrupt):
        return False


def send_keys(codes: list[int]) -> None:
    import win32api
    import win32con

    pressed = []
    try:
        for code in codes:
            win32api.keybd_event(code, 0, 0, 0)
            pressed.append(code)
    finally:
        for code in reversed(pressed):
            win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=MEDIA_KEYS, default="toggle")
    parser.add_argument("--hotkey", help="从酷狗设置页抄录的全局热键，例如 ctrl+alt+p；不猜默认键")
    parser.add_argument("--execute", action="store_true", help="提示并确认后发送一次")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        codes = hotkey_codes(args.hotkey) if args.hotkey else [MEDIA_KEYS[args.action]]
    except ValueError as exc:
        parser.error(str(exc))
    data = {"action": args.action, "hotkey": args.hotkey, "virtual_keys": codes,
            "sent": False, "verified": False, "warning": WARNING}
    if not args.execute:
        emit(envelope("KugouMedia", "ok", data=data,
                      hint="只读预览；--execute 后还须交互确认。发送成功也不等于生效。"), args.output)
        return
    print(WARNING, flush=True)
    require_windows()
    if not processes():
        emit(envelope("KugouMedia", "not_running", data=data), args.output)
        raise SystemExit(2)
    if not confirm():
        emit(envelope("KugouMedia", "cancelled", data=data), args.output)
        return
    try:
        send_keys(codes)
    except Exception as exc:
        emit(envelope("KugouMedia", "error", data=data,
                      error=f"发送失败，可能已部分执行，请检查酷狗：{type(exc).__name__}: {exc}"), args.output)
        raise SystemExit(2) from exc
    data["sent"] = True
    emit(envelope("KugouMedia", "ok", data=data,
                  hint="已尝试发送，尚未核验；比较窗口、SMTC 和酷狗实际画面后记录结论。"), args.output)


if __name__ == "__main__":
    main()
