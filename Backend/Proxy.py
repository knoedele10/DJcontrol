"""反向代理：界面留在容器里，/api 与 /ws 转发到 Windows 上的 COM 宿主进程。

容器是 Linux，既没有 PowerPoint/WPS、酷狗窗口，也装不上只有 Windows 版本的 pywin32。
设置 API_UPSTREAM（例如 http://host.docker.internal:8081）后，容器只负责出界面，
所有接口和 WebSocket 都转发给该地址，由 Windows 侧的单进程完成 COM 操作。

不引入 httpx 之类的客户端依赖：镜像里只装了 requirements.txt，转发用标准库即可。
"""

from __future__ import annotations

import asyncio
import logging
import urllib.error
import urllib.request
from contextlib import suppress
from urllib.parse import urlsplit

import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 逐跳首部只对单跳连接有意义，转发时必须丢掉；content-length 由新的响应重新计算。
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def normalize_upstream(raw: str) -> str:
    """校验并规整上游地址；配置写错就直接启动失败，不要带着坏地址跑。"""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("API_UPSTREAM 必须是 http(s)://主机:端口 形式")
    return value


def websocket_upstream(base: str) -> str:
    """把 http(s):// 换成 ws(s)://，其余部分原样保留。"""
    return "ws" + base[len("http"):] if base.startswith("http") else base


def _forward_blocking(
    method: str, url: str, headers: list[tuple[str, str]], body: bytes, timeout: float
) -> tuple[int, list[tuple[str, str]], bytes]:
    request = urllib.request.Request(url, data=body or None, method=method)
    for name, value in headers:
        # 客户端自带的 host 会指向容器，必须让 urllib 用上游的主机名重新生成。
        if name.lower() in HOP_BY_HOP:
            continue
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, list(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        # 4xx/5xx 也要原样交给前端：面板靠错误码区分"未连接"和"参数不对"。
        with error:
            return error.code, list(error.headers.items()), error.read()


def _upstream_unavailable(upstream: str, exc: BaseException) -> JSONResponse:
    logger.warning("转发到 %s 失败：%s", upstream, exc)
    return JSONResponse(
        status_code=502,
        content={
            "detail": {
                "code": "upstream_unavailable",
                "message": "连不上 Windows 后端，请确认它已启动，且 API_UPSTREAM 指向正确的端口",
            }
        },
    )


async def forward_http(request: Request, upstream: str, timeout: float = 120.0) -> Response:
    """把当前请求原样转发给上游，返回上游的响应。"""
    url = f"{upstream}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    body = await request.body()
    try:
        status, headers, content = await asyncio.to_thread(
            _forward_blocking, request.method, url, list(request.headers.items()), body, timeout
        )
    except (urllib.error.URLError, OSError) as exc:
        return _upstream_unavailable(upstream, exc)
    forwarded = {name: value for name, value in headers if name.lower() not in HOP_BY_HOP}
    return Response(content=content, status_code=status, headers=forwarded)


async def _pump(websocket: WebSocket, client: websockets.ClientConnection) -> None:
    async def downstream() -> None:
        """上游 → 前端。"""
        async for message in client:
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)

    async def upstream_direction() -> None:
        """前端 → 上游。"""
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await client.send(message["text"])
            elif message.get("bytes") is not None:
                await client.send(message["bytes"])

    tasks = [asyncio.create_task(downstream()), asyncio.create_task(upstream_direction())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def forward_websocket(websocket: WebSocket, upstream: str) -> None:
    target = websocket_upstream(upstream) + websocket.url.path
    if websocket.url.query:
        target = f"{target}?{websocket.url.query}"
    await websocket.accept()
    try:
        # ping 交给两端各自处理，代理只做消息透传，不再插一条心跳。
        async with websockets.connect(target, open_timeout=10, ping_interval=None) as client:
            await _pump(websocket, client)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("WebSocket 转发失败：%s", target, exc_info=True)
        with suppress(Exception):
            await websocket.close(code=1011)
    else:
        with suppress(Exception):
            await websocket.close()


def install(application: FastAPI, upstream: str) -> None:
    """在 /api/health 之后挂上转发路由；catch-all 必须排在具体路由后面。"""

    @application.api_route("/api/{path:path}", methods=METHODS, include_in_schema=False)
    async def proxy_api(request: Request, path: str) -> Response:
        return await forward_http(request, upstream)

    @application.websocket("/ws/{path:path}")
    async def proxy_ws(websocket: WebSocket, path: str) -> None:
        await forward_websocket(websocket, upstream)
