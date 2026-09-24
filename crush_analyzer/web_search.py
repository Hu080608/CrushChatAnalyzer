"""免费联网搜索梗 / 游戏 / 网络用语。

使用 B 站公开搜索接口获取视频标题作为上下文，不需要 API Key。
失败时静默返回空列表，不影响自动回复。
"""
from __future__ import annotations

import html
import json
import re
from typing import List, Optional
import urllib.parse
import urllib.request

from .logs import get_logger
from .net import urlopen

logger = get_logger("web_search")
_BILIBILI_SEARCH = "https://api.bilibili.com/x/web-interface/search/type"


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).replace("\n", " ").strip()


def search_meme(query: str, limit: int = 3, timeout: int = 6) -> List[str]:
    query = (query or "").strip()
    if not query or len(query) > 40:
        return []
    try:
        params = urllib.parse.urlencode(
            {"search_type": "video", "keyword": query, "page": 1}
        )
        request = urllib.request.Request(
            f"{_BILIBILI_SEARCH}?{params}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        if data.get("code") != 0:
            logger.info("B站搜索返回 code=%s", data.get("code"))
            return []
        results = ((data.get("data") or {}).get("result") or [])
        out: List[str] = []
        for item in results[: max(1, int(limit))]:
            title = _strip_tags(str(item.get("title") or ""))
            if not title:
                continue
            out.append(title)
        logger.info("联网搜索 %r 得到 %s 条参考", query, len(out))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("联网搜索失败 %r: %s", query, exc)
        return []


def build_web_context(query: str, limit: int = 3) -> str:
    results = search_meme(query, limit=limit)
    if not results:
        return ""
    return "；".join(results)
