"""酷狗歌曲搜索：直接查酷狗的网络搜索接口，不操作酷狗窗口。

客户端的搜索结果页是画出来的，读不到文字；网络接口返回的是同一个曲库的结果。
这个接口不是酷狗公开承诺的，随时可能变：任何异常都只算"这次没搜到"，不影响曲库搜索。
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

SEARCH_URL = "http://mobilecdn.kugou.com/api/v3/search/song"
_TAG = re.compile(r"<[^>]+>")
_HINT = re.compile(r"【[^】]*(?:】|$)")  # 酷狗会在歌名后面拼「【大家还在搜：…】」之类的推广词


class KugouSearchFailed(Exception):
    pass


def _clean(text: object) -> str:
    return " ".join(_HINT.sub("", _TAG.sub("", str(text or ""))).split())


def parse(payload: dict) -> list[dict]:
    rows = (payload.get("data") or {}).get("info") or []
    results = []
    for row in rows:
        title, artist = _clean(row.get("songname")), _clean(row.get("singername"))
        if title:
            results.append({"title": title, "artist": artist, "duration": max(int(row.get("duration") or 0), 0)})
    return results


def search(query: str, limit: int = 30, timeout: float = 7.0) -> list[dict]:
    """返回 [{title, artist, duration}]，顺序与酷狗一致。"""

    url = SEARCH_URL + "?" + urllib.parse.urlencode({"format": "json", "keyword": query, "page": 1, "pagesize": limit})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        if not isinstance(payload, dict) or payload.get("status") != 1:
            raise ValueError("unexpected response")
        return parse(payload)[:limit]
    except Exception as exc:
        raise KugouSearchFailed(f"酷狗搜索接口不可用：{exc}") from exc
