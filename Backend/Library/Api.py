"""M2 曲库、搜索、活动组和分类 HTTP/WebSocket 路由。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, WebSocket, WebSocketDisconnect

from Library.Model import (
    CategoryCreate, CategoryPatch, CategorySong, CategorySongs, GroupCreate, GroupPatch,
    CategoryOrderRequest, GroupOrderRequest, ImportSongs, KugouImport, SongCreate, SongPatch,
)
from Library.Service import (
    KugouUnavailable, LibraryConflict, LibraryError, LibraryNotFound, LibraryService,
)

router = APIRouter()


def service(request: Request) -> LibraryService:
    return request.app.state.library


def error_response(exc: LibraryError) -> HTTPException:
    status = 503 if isinstance(exc, KugouUnavailable) else 409 if isinstance(exc, LibraryConflict) else 404 if isinstance(exc, LibraryNotFound) else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/api/songs")
async def songs(request: Request, source: str | None = Query(default=None, pattern="^(library|kugou)$")) -> list[dict]:
    return await service(request).songs(source)


@router.post("/api/songs", status_code=201)
async def create_song(body: SongCreate, request: Request) -> dict:
    try:
        return await service(request).create_song(body.model_dump())
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.post("/api/songs/import")
async def import_songs(body: ImportSongs, request: Request) -> dict:
    try:
        return await service(request).import_songs(body.text, body.category_ids)
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.patch("/api/songs/{song_id}")
async def update_song(body: SongPatch, request: Request, song_id: int = Path(..., ge=0)) -> dict:
    try:
        return await service(request).update_song(song_id, body.model_dump(exclude_unset=True))
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.delete("/api/songs/{song_id}", status_code=204)
async def delete_song(request: Request, song_id: int = Path(..., ge=0)) -> Response:
    try:
        await service(request).delete_song(song_id)
    except LibraryError as exc:
        raise error_response(exc) from exc
    return Response(status_code=204)


@router.post("/api/songs/from-kugou", status_code=201)
async def import_kugou(body: KugouImport, request: Request) -> dict:
    try:
        return await service(request).import_kugou(body.key)
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.get("/api/search")
async def search(
    request: Request,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    source: str = Query(default="all", pattern="^(all|library|kugou)$"),
) -> dict:
    # 酷狗要查网络，可能要好几秒；前端先用 source=library 拿曲库结果，再用 source=kugou 补酷狗结果。
    # 酷狗失败或超时只是没有酷狗结果，不影响曲库结果。
    async def nothing():
        return []

    async def no_kugou():
        return [], False

    library, (kugou, available) = await asyncio.gather(
        service(request).search(q, limit) if source != "kugou" else nothing(),
        service(request).search_kugou(q, limit) if source != "library" else no_kugou())
    return {"query": q, "library": library, "kugou": kugou, "kugou_available": available}


@router.get("/api/groups")
async def groups(request: Request) -> list[dict]:
    return await service(request).groups()


@router.post("/api/groups", status_code=201)
async def create_group(body: GroupCreate, request: Request) -> dict:
    try:
        return await service(request).create_group(body.name, body.color)
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.patch("/api/groups/{group_id}")
async def update_group(body: GroupPatch, group_id: str, request: Request) -> dict:
    try:
        return await service(request).update_group(group_id, body.model_dump(exclude_unset=True))
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.delete("/api/groups/{group_id}", status_code=204)
async def delete_group(group_id: str, request: Request) -> Response:
    try:
        await service(request).delete_group(group_id)
    except LibraryError as exc:
        raise error_response(exc) from exc
    return Response(status_code=204)


@router.put("/api/groups/order", status_code=204)
async def reorder_groups(body: GroupOrderRequest, request: Request) -> Response:
    try:
        await service(request).reorder_groups(body.group_ids)
    except LibraryError as exc:
        raise error_response(exc) from exc
    return Response(status_code=204)


@router.post("/api/groups/{group_id}/categories", status_code=201)
async def create_category(body: CategoryCreate, group_id: str, request: Request) -> dict:
    try:
        return await service(request).create_category(group_id, body.name, body.color, body.song_ids)
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.patch("/api/categories/{category_id}")
async def update_category(body: CategoryPatch, category_id: str, request: Request) -> dict:
    try:
        return await service(request).update_category(category_id, body.model_dump(exclude_unset=True))
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.delete("/api/categories/{category_id}", status_code=204)
async def delete_category(category_id: str, request: Request) -> Response:
    try:
        await service(request).delete_category(category_id)
    except LibraryError as exc:
        raise error_response(exc) from exc
    return Response(status_code=204)


@router.put("/api/groups/{group_id}/categories/order", status_code=204)
async def reorder_categories(body: CategoryOrderRequest, group_id: str, request: Request) -> Response:
    try:
        await service(request).reorder_categories(group_id, body.category_ids)
    except LibraryError as exc:
        raise error_response(exc) from exc
    return Response(status_code=204)


@router.post("/api/categories/{category_id}/songs")
async def add_category_song(body: CategorySong, category_id: str, request: Request) -> dict:
    try:
        return await service(request).category_song(category_id, body.song_id, True)
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.delete("/api/categories/{category_id}/songs/{song_id}")
async def remove_category_song(category_id: str, request: Request, song_id: int = Path(..., ge=0)) -> dict:
    try:
        return await service(request).category_song(category_id, song_id, False)
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.put("/api/categories/{category_id}/songs")
async def replace_category_songs(body: CategorySongs, category_id: str, request: Request) -> dict:
    try:
        return await service(request).replace_category_songs(category_id, body.song_ids)
    except LibraryError as exc:
        raise error_response(exc) from exc


@router.websocket("/ws/library")
async def library_events(websocket: WebSocket) -> None:
    await websocket.accept()
    library: LibraryService = websocket.app.state.library
    queue = library.subscribe()

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
        library.unsubscribe(queue)
