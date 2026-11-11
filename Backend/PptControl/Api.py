"""PPT 控制和状态订阅接口。"""

import asyncio

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, WebSocket, WebSocketDisconnect

from PptControl import PptApp, PptError, PptUnavailable
from PptControl.Model import PptBinding, PptBindingImport, PptCommand, PptConnection, PptSettings

router = APIRouter()


@router.get("/api/ppt/preview/{slide}")
async def preview(
    request: Request,
    slide: int = Path(..., ge=1),
    app: PptApp = Query(...),
    document: str = Query(..., min_length=1),
    width: int = Query(default=1280, ge=160, le=1600),
    version: int = Query(default=0, ge=0),
    session: str = Query(default="", max_length=64),
) -> Response:
    try:
        content = await request.app.state.ppt.preview(app, document, slide, width, version, session)
    except PptError as exc:
        raise HTTPException(
            status_code=503 if isinstance(exc, PptUnavailable) else 409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return Response(content=content, media_type="image/png", headers={
        "Cache-Control": "private, max-age=31536000, immutable" if session else "no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/api/ppt/state")
async def state(request: Request) -> dict:
    return await request.app.state.ppt.refresh()


@router.post("/api/ppt/connect")
async def connect(body: PptConnection, request: Request) -> dict:
    return await request.app.state.ppt.connect(body.app)


@router.post("/api/ppt/command")
async def command(body: PptCommand, request: Request) -> dict:
    try:
        return await request.app.state.ppt.command(body)
    except PptError as exc:
        raise HTTPException(
            status_code=503 if isinstance(exc, PptUnavailable) else 409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


def _failed(exc: PptError) -> HTTPException:
    return HTTPException(status_code=503 if isinstance(exc, PptUnavailable) else 409,
                         detail={"code": exc.code, "message": str(exc)})


@router.put("/api/ppt/bindings/{slide}")
async def bind(body: PptBinding, request: Request, slide: int = Path(..., ge=1)) -> dict:
    """把当前文稿的某一页绑定到一首歌；song_id 为 null 表示解除。"""

    try:
        return await request.app.state.ppt_link.bind(slide, body.song_id)
    except PptError as exc:
        raise _failed(exc) from exc


@router.post("/api/ppt/bindings/import")
async def import_bindings(body: PptBindingImport, request: Request) -> dict:
    return await request.app.state.ppt_link.import_bindings(body.bindings)


@router.patch("/api/ppt/settings")
async def settings(body: PptSettings, request: Request) -> dict:
    return await request.app.state.ppt_link.set_link_music(body.link_music)


@router.websocket("/ws/ppt")
async def subscribe(websocket: WebSocket) -> None:
    await websocket.accept()
    service = websocket.app.state.ppt
    queue = service.subscribe()

    async def send() -> None:
        while True:
            try:
                update = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                update = {"type": "ping"}
            await websocket.send_json(update)

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
