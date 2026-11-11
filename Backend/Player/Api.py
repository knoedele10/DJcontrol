"""M3 播放器、队列、场次和已播接口。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, WebSocket, WebSocketDisconnect

from Player.Model import ControllerSettings, PlayerCommand, PlayerSettings, QueueCreate, QueueOrder
from Player.Service import PlayerConflict, PlayerError, PlayerNotFound, PlayerService

router = APIRouter()


def player(request: Request) -> PlayerService:
    return request.app.state.player


def error_response(exc: PlayerError) -> HTTPException:
    status = {"not_found": 404, "player_unavailable": 503, "command_timeout": 504}.get(exc.code, 409)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/api/player/state")
async def state(request: Request) -> dict:
    return await player(request).refresh()


@router.post("/api/player/command")
async def command(body: PlayerCommand, request: Request) -> dict:
    try:
        return await player(request).command(body)
    except PlayerError as exc:
        raise error_response(exc) from exc


@router.patch("/api/player/settings")
async def settings(body: PlayerSettings, request: Request) -> dict:
    try:
        return await player(request).set_auto_next(body.auto_next)
    except PlayerError as exc:
        raise error_response(exc) from exc


@router.get("/api/diagnostics")
async def diagnostics(request: Request) -> dict:
    service = player(request)
    await service.refresh()
    result = await service.diagnostics()
    ppt = request.app.state.ppt.state
    result["ppt"] = {"app": ppt.app, "connected": ppt.connected}
    return result


@router.post("/api/diagnostics/refresh")
async def refresh_diagnostics(request: Request) -> dict:
    return await diagnostics(request)


@router.put("/api/settings/controller")
async def controller_settings(body: ControllerSettings, request: Request) -> dict:
    await player(request).switch_controller(body.name)
    return await diagnostics(request)


@router.post("/api/queue")
async def enqueue(body: QueueCreate, request: Request) -> dict:
    try:
        return await player(request).enqueue(body.song_id, body.position)
    except PlayerError as exc:
        raise error_response(exc) from exc


@router.delete("/api/queue/{item_id}")
async def remove_queue(item_id: str, request: Request) -> dict:
    try:
        return await player(request).remove_queue_item(item_id)
    except PlayerError as exc:
        raise error_response(exc) from exc


@router.put("/api/queue/order")
async def order_queue(body: QueueOrder, request: Request) -> dict:
    try:
        return await player(request).order_queue(body.item_ids)
    except PlayerError as exc:
        raise error_response(exc) from exc


@router.delete("/api/queue")
async def clear_queue(request: Request) -> dict:
    return await player(request).clear_queue()


@router.post("/api/sessions")
async def start_session(request: Request) -> dict:
    return await player(request).start_session()


@router.post("/api/sessions/current/end")
async def end_session(request: Request) -> dict:
    return await player(request).end_session()


@router.get("/api/history")
async def history(
    request: Request,
    session: str = Query(default="current"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    if session != "current":
        raise HTTPException(status_code=422, detail={"code": "invalid_session", "message": "当前只支持 session=current"})
    return await player(request).history(limit)


@router.websocket("/ws/player")
async def player_events(websocket: WebSocket) -> None:
    await websocket.accept()
    service: PlayerService = websocket.app.state.player
    queue = service.subscribe()

    async def send() -> None:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                event = {"type": "ping"}
            await websocket.send_json(event)

    async def receive() -> None:
        while True:
            await websocket.receive_text()

    tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        service.unsubscribe(queue)
