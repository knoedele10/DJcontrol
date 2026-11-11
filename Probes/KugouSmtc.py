"""读取系统媒体会话，仅输出酷狗曲目，不控制会话或泄露其他应用的曲目。"""

import argparse
import asyncio
from typing import Any

from KugouCommon import cli, processes


def is_kugou_source(source: str) -> bool:
    return "kugou" in source.casefold() or "酷狗" in source


async def sessions() -> dict[str, Any]:
    import winrt.windows.foundation  # noqa: F401，注册异步桥接类型
    import winrt.windows.foundation.collections  # noqa: F401
    import winrt.windows.media  # noqa: F401
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    all_sessions = list(manager.get_sessions())
    result = []
    for session in all_sessions:
        source = session.source_app_user_model_id
        if not is_kugou_source(source):
            continue
        media = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        timeline = session.get_timeline_properties()
        result.append({"source_app_id": source, "title": media.title, "artist": media.artist,
                       "playback_status": playback.playback_status.name,
                       "position": timeline.position.total_seconds(),
                       "start": timeline.start_time.total_seconds(),
                       "end": timeline.end_time.total_seconds(),
                       "last_updated": timeline.last_updated_time.isoformat()})
    return {"running": bool(processes()), "kugou_sessions": result,
            "other_session_count": len(all_sessions) - len(result),
            "available": bool(result), "matching": "source app id contains Kugou/酷狗"}


def read(args: argparse.Namespace) -> dict[str, Any]:
    return asyncio.run(sessions())


if __name__ == "__main__":
    cli("KugouSmtc", read)
