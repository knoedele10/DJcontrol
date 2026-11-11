"""每次隔离操作在同一主线程创建/释放 COM，父进程可终止卡死的 UIA。"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time

from KugouControl.Profiles import match, parse_title
from KugouControl.Version import discover


def read() -> dict:
    info = discover()
    if "error" in info:
        return {"connected": False, "status": "unknown", "error": info["error"], "running": False}
    title, artist = parse_title(info.pop("window_title"))
    result = {**info, "running": True, "connected": True, "title": title, "artist": artist,
              "status": "unknown", "controls_ready": False, "profile": match(info["version"]), "error": None}
    if not result["profile"]:
        result["error"] = "酷狗版本尚未验证，请更新适配档案"
    elif info["minimized"]:
        result["error"] = "酷狗窗口已最小化或收起至托盘，请恢复窗口后控制"
    elif info.get("blocked"):
        result["error"] = "酷狗弹窗正在阻止操作，请先处理酷狗弹窗"
    else:
        from KugouControl.Uia import read_controls
        try:
            result.update(read_controls(info["hwnd"]))
            if not result["controls_ready"]:
                result["error"] = "无法定位酷狗播放栏，请关闭弹窗、收起歌词详情页并恢复音乐主界面"
        except Exception:
            from KugouControl.Uia import invalidate
            invalidate()
            logging.exception("读取酷狗播放栏失败")
            result["error"] = "读取酷狗控件失败，请检查窗口与权限级别"
    if result.get("controls_ready"):
        fresh = discover()
        if fresh.get("pid") == info["pid"]:
            result["title"], result["artist"] = parse_title(fresh.get("window_title", ""))
    if not result.get("title"):
        # 切歌加载期间标题为空，滑块最大值还是上一首的时长，这时的进度不可信。
        result["position"] = result["duration"] = None
    return result


def operate(line: str) -> dict:
    # 带参数的命令写成「动作 JSON」，例如 seek {"position": 30}。
    action, _, raw = line.partition(" ")
    options = json.loads(raw) if raw else {}
    before = read()
    if action == "read":
        return {"data": before}
    if not before.get("connected"):
        return {"error": "player_unavailable", "message": before["error"], "data": before}
    if not before.get("profile"):
        return {"error": "capability_unsupported", "message": "当前酷狗版本未验证，已停止发送按键", "data": before}
    if before.get("error") or not before.get("controls_ready"):
        return {"error": "player_unavailable", "message": before.get("error"), "data": before}
    if action in ("play_track", "seek"):
        from KugouControl import Track
        try:
            if action == "seek":
                Track.seek(before["hwnd"], float(options["position"]))
            else:
                Track.play_track(before["hwnd"], before["pid"], options["title"], options.get("artist", ""))
        except Track.TrackLoading as exc:
            return {"error": "track_loading", "message": str(exc), "data": read()}
        except Track.TrackFailed as exc:
            return {"error": "player_command_failed", "message": str(exc), "data": read()}
        return {"data": read(), "sent": True}
    from KugouControl.Media import send
    send(action)
    from KugouControl.Uia import invalidate
    invalidate()
    time.sleep(0.15)
    # 仅确认发送。服务在 finally 刷新真实状态后，由父控制器比较前后快照。
    return {"data": before, "sent": True}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        # UIA 客户端使用 MTA；常驻 STA 在等待 stdin 时没有消息循环，会卡住跨进程 COM。
        sys.coinit_flags = 0
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        try:
            if sys.argv[1] == "--serve":
                for action in sys.stdin:
                    try:
                        result = operate(action.strip())
                    except subprocess.TimeoutExpired:
                        logging.exception("酷狗输入进程超时")
                        result = {"error": "command_timeout", "message": "酷狗输入进程超时，命令不会自动重试"}
                    except Exception:
                        logging.exception("酷狗操作失败")
                        result = {"error": "player_unavailable", "message": "酷狗操作失败，请检查窗口与权限"}
                    print(json.dumps(result, ensure_ascii=False), flush=True)
            else:
                result = operate(sys.argv[1])
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        logging.exception("酷狗隔离进程失败")
        result = {"error": "player_unavailable", "message": "酷狗控制环境不可用，请检查依赖与桌面会话"}
    if sys.argv[1] != "--serve":
        print(json.dumps(result, ensure_ascii=False), flush=True)
