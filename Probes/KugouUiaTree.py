"""导出酷狗原始 UIA 控件，不点击、恢复窗口或改变搜索内容。"""

import argparse
from typing import Any

from KugouCommon import cli, processes, windows


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hwnd", type=int, help="窗口不唯一时从 window 探测结果选择")
    parser.add_argument("--depth", type=int, choices=range(1, 41), default=8, metavar="1..40")
    parser.add_argument("--max-nodes", type=int, choices=range(1, 2001), default=500, metavar="1..2000")
    parser.add_argument("--backend", choices=["uia", "win32"], default="uia")
    parser.add_argument("--values", action="store_true", help="读取数值 pattern，可能较慢")


def readable_edit(info: Any) -> bool:
    """歌单筛选框可能没有名称；同时继续排除密码与明显的账户设置字段。"""
    if info.name in ('用户名', '账号', '账户', '密码', '代理地址', '端口'):
        return False
    try:
        return not info.element.CurrentIsPassword
    except Exception:
        return False


def read(args: argparse.Namespace) -> dict[str, Any]:
    from pywinauto import Desktop

    running = processes()
    candidates = [window for window in windows(running) if window["visible"]]
    if args.hwnd is not None:
        candidates = [window for window in candidates if window["hwnd"] == args.hwnd]
    else:
        candidates = [window for window in candidates if "酷狗" in window["title"]]
    if len(candidates) != 1:
        return {"running": bool(running), "available": False,
                "reason": "没有唯一可见的主窗口，请用 --hwnd 选择", "candidates": candidates}
    window = candidates[0]
    root = Desktop(backend=args.backend).window(handle=window["hwnd"]).wrapper_object()
    nodes = []
    truncated = False

    def walk(control: Any, depth: int) -> None:
        nonlocal truncated
        if len(nodes) >= args.max_nodes:
            truncated = True
            return
        info = control.element_info
        rect = info.rectangle
        node = {"depth": depth, "name": info.name, "class_name": info.class_name,
                      "control_type": getattr(info, "control_type", None),
                      "automation_id": getattr(info, "automation_id", None),
                      "enabled": info.enabled, "visible": info.visible,
                      "rect": [rect.left, rect.top, rect.right, rect.bottom]}
        read_value = (node["control_type"] == "Slider"
                      or (node["control_type"] == "Edit" and readable_edit(info))
                      or (node["control_type"] == "Text" and " - " in node["name"]))
        if args.values and args.backend == "uia" and node["visible"] and read_value:
            for pattern, fields in (("iface_value", ("CurrentValue",)),
                                    ("iface_range_value", ("CurrentValue", "CurrentMinimum", "CurrentMaximum"))):
                try:
                    iface = getattr(control, pattern)
                    node[pattern] = {field: getattr(iface, field) for field in fields}
                except Exception:
                    # 控件不提供该 pattern 是正常情况，不能猜测一个值。
                    pass
        nodes.append(node)
        children = control.children()
        if depth >= args.depth:
            truncated = truncated or bool(children)
            return
        for child in children:
            walk(child, depth + 1)
            if len(nodes) >= args.max_nodes:
                truncated = True
                break

    walk(root, 0)
    return {"running": True, "available": True, "backend": args.backend,
            "window": window, "node_count": len(nodes), "truncated": truncated, "nodes": nodes}


if __name__ == "__main__":
    cli("KugouUiaTree", read, configure)
