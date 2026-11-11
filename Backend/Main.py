"""FastAPI 服务入口：uvicorn Main:app --host 127.0.0.1 --port 8000。"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from Library.Api import router as library_router
from Player.Api import router as player_router
from PptControl.Api import router as ppt_router
from Database import Database, SettingsRepository
from Proxy import install as install_proxy
from Proxy import normalize_upstream
from Library.Service import LibraryService
from Player.Service import PlayerService
from PptControl.Link import PptLink
from PptControl.Service import PptService
from Player.Model import PlayerCommand


def create_app(
    ppt_service: PptService | None = None,
    database: Database | None = None,
    player_service: PlayerService | None = None,
    upstream: str | None = None,
) -> FastAPI:
    configured = normalize_upstream(
        upstream if upstream is not None else os.environ.get("API_UPSTREAM", "")
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if configured:
            # 代理模式：容器不建库、不连 COM，状态全在 Windows 那一端。
            yield
            return
        selected = os.environ.get("PPT_APP", "powerpoint").lower()
        if selected not in ("powerpoint", "wps"):
            raise ValueError("PPT_APP 必须为 powerpoint 或 wps")
        service = ppt_service or PptService(app=selected)
        db = database or Database()
        kugou_search = os.environ.get("KUGOU_SEARCH", "on").lower()
        if kugou_search not in ("on", "off"):
            raise ValueError("KUGOU_SEARCH 必须为 on 或 off")
        if kugou_search == "on":
            from KugouControl.Search import search as kugou_searcher
        library = LibraryService(db, kugou_search=kugou_searcher if kugou_search == "on" else None)
        player_controller = os.environ.get("PLAYER_CONTROLLER", "mock").lower()
        if player_controller not in ("mock", "kugou"):
            raise ValueError("PLAYER_CONTROLLER 必须为 mock 或 kugou")
        db.connect()
        if "PLAYER_CONTROLLER" not in os.environ:
            player_controller = SettingsRepository(db).get("player.controller", "mock")
            if player_controller not in ("mock", "kugou"):
                db.close()
                raise ValueError("保存的播放器配置无效")
        playback = player_service or PlayerService(db, controller_name=player_controller)
        application.state.ppt = service
        application.state.db = db
        application.state.library = library
        application.state.player = playback

        async def play_for_slide(song_id: int) -> bool:
            if playback.state.song_id == song_id and playback.state.status == "playing":
                return False
            await playback.command(PlayerCommand(action="play", song_id=song_id))
            return True

        link = None
        try:
            # 数据库先完成迁移和种子，再启动依赖它的业务服务。
            db.connect()
            link = application.state.ppt_link = PptLink(db, service, play_for_slide)
            await service.start()
            await playback.start()
            yield
        finally:
            if link is not None:
                await link.close()
            await playback.close()
            await library.close()
            await service.close()
            db.close()

    application = FastAPI(title="演出控制面板", lifespan=lifespan)

    @application.get("/api/health")
    async def health() -> dict:
        # 代理模式下健康检查仍然只看容器自己：上游没起来不应该让容器反复重启。
        if configured:
            return {"status": "ok", "mode": "proxy", "upstream": configured}
        return {"status": "ok"}

    if configured:
        # 具体路由 /api/health 先注册，catch-all 才能把其余接口转发出去。
        install_proxy(application, configured)
    else:
        application.include_router(library_router)
        application.include_router(player_router)
        application.include_router(ppt_router)

    # 容器部署时由同一个进程提供前端构建产物；开发环境不设置该变量，继续用 Vite。
    frontend_dist = os.environ.get("FRONTEND_DIST")
    if frontend_dist and Path(frontend_dist).is_dir():
        application.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return application


app = create_app()
