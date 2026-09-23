"""内置示例聊天数据。

这样打包成单文件 exe 后，即使没有 examples 目录，第一次使用也能直接导入示例。
"""
from __future__ import annotations

from pathlib import Path
import tempfile


SAMPLE_CHAT_TEXT = """我 2024-01-01 20:00:00
今天过得怎么样呀？

对方 2024-01-01 20:05:00
还不错，今天吃了好吃的哈哈

我 2024-01-01 20:07:00
那太好啦，是什么好吃的？

对方 2024-01-01 20:10:00
火锅，下次带你

对方 2024-01-01 20:11:00
对了，你周末有空吗？
"""


def write_sample_chat(directory: str | Path | None = None) -> Path:
    """把内置示例写到临时文件，返回文件路径。"""
    base = Path(directory) if directory else Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    path = base / "crush_chat_sample.txt"
    path.write_text(SAMPLE_CHAT_TEXT, encoding="utf-8")
    return path
