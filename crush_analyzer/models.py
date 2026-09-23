"""数据模型。

所有模块共享的小型数据类，尽量不引入 GUI 或网络依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


def new_id() -> str:
    return uuid.uuid4().hex


def format_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


_INVISIBLE_NAME_CHARS = (
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\u2060",  # word joiner
    "\ufeff",  # BOM
    "\ufffd",  # replacement character
    "\u25a1",  # white square
    "\u25a0",  # black square
    "\u25af",  # white vertical rectangle
)

_NAME_WHITESPACE = " \t\r\n\u00a0\u3000"


def clean_name(value: Any) -> str:
    """清理昵称里的空格、不可见占位符和开头 @ / #。"""
    text = str(value or "")
    for ch in _INVISIBLE_NAME_CHARS:
        text = text.replace(ch, "")
    text = "".join(ch for ch in text if ch not in _NAME_WHITESPACE)
    text = text.strip()
    while text.startswith(("@", "#")):
        text = text[1:].lstrip()
    return text


def parse_dt(value: Any) -> Optional[datetime]:
    """尽量把各种输入转换为 datetime。无法解析时返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # 微信时间戳通常是秒，少数导出工具使用毫秒
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    # 先试 ISO 风格
    candidates = [
        text,
        text.replace("年", "-").replace("月", "-").replace("日", " "),
        text.replace("/", "-"),
        text.replace(".", "-"),
    ]
    patterns = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%m-%d %H:%M",
        "%H:%M:%S",
        "%H:%M",
    ]
    for cand in candidates:
        cand = cand.strip()
        for fmt in patterns:
            try:
                return datetime.strptime(cand, fmt)
            except ValueError:
                continue
    return None


@dataclass
class Message:
    """一条聊天消息。"""

    sender: str
    content: str
    timestamp: Optional[datetime] = None
    is_self: bool = False
    message_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_row(self, session_id: str) -> tuple:
        import json

        return (
            self.message_id or new_id(),
            session_id,
            self.sender,
            self.content,
            format_dt(self.timestamp),
            int(bool(self.is_self)),
            json.dumps(self.raw, ensure_ascii=False),
        )

    @classmethod
    def from_row(cls, row: Any) -> "Message":
        import json

        raw = {}
        if row["raw"]:
            try:
                raw = json.loads(row["raw"])
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = {}
        return cls(
            message_id=row["message_id"],
            sender=clean_name(row["sender"]),
            content=row["content"] or "",
            timestamp=parse_dt(row["timestamp"]),
            is_self=bool(row["is_self"]),
            raw=raw,
        )

    def short(self, limit: int = 60) -> str:
        content = self.content.replace("\n", " ")
        return content if len(content) <= limit else content[: limit - 1] + "…"


@dataclass
class ChatSession:
    """一次导入或接入的会话。"""

    id: str = field(default_factory=new_id)
    name: str = "未命名会话"
    platform: str = "wechat"
    source: str = ""  # 文件路径或 wxauto 会话名
    self_sender: str = ""  # 用户在聊天里的昵称
    other_sender: str = ""  # 对方昵称
    created_at: Optional[datetime] = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = field(default_factory=datetime.now)
    messages: List[Message] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def senders(self) -> List[str]:
        seen: List[str] = []
        for m in self.messages:
            if m.sender and m.sender not in seen:
                seen.append(m.sender)
        return seen

    @property
    def self_messages(self) -> List[Message]:
        return [m for m in self.messages if m.is_self]

    @property
    def other_messages(self) -> List[Message]:
        return [m for m in self.messages if not m.is_self]

    def to_row(self) -> tuple:
        return (
            self.id,
            clean_name(self.name),
            self.platform,
            self.source,
            clean_name(self.self_sender),
            clean_name(self.other_sender),
            format_dt(self.created_at),
            format_dt(self.updated_at),
            __import__("json").dumps(self.meta, ensure_ascii=False),
        )

    @classmethod
    def from_row(cls, row: Any, messages: Optional[List[Message]] = None) -> "ChatSession":
        import json

        meta: Dict[str, Any] = {}
        if row["meta"]:
            try:
                meta = json.loads(row["meta"])
            except (TypeError, ValueError, json.JSONDecodeError):
                meta = {}
        return cls(
            id=row["id"],
            name=clean_name(row["name"]) or "未命名会话",
            platform=row["platform"] or "wechat",
            source=row["source"] or "",
            self_sender=clean_name(row["self_sender"]),
            other_sender=clean_name(row["other_sender"]),
            created_at=parse_dt(row["created_at"]) or datetime.now(),
            updated_at=parse_dt(row["updated_at"]) or datetime.now(),
            messages=list(messages or []),
            meta=meta,
        )

    def normalize_roles(self, self_sender: str) -> None:
        """根据“我是谁”重新标记 is_self。"""
        self.self_sender = (self_sender or "").strip()
        for m in self.messages:
            if self.self_sender:
                m.is_self = m.sender.strip() == self.self_sender
            elif m.sender:
                # 没有明确昵称时保留导入器给出的判断
                pass
        # 如果对方昵称尚未确定，尝试推断一下
        if not self.other_sender and self.self_sender:
            for m in self.messages:
                if m.sender and m.sender.strip() != self.self_sender:
                    self.other_sender = m.sender.strip()
                    break


@dataclass
class AnalysisRecord:
    id: Optional[int]
    session_id: str
    kind: str
    model: str
    content: str
    created_at: Optional[datetime] = None


@dataclass
class ImportResult:
    session: ChatSession
    warnings: List[str] = field(default_factory=list)
    detected_format: str = ""

    def asdict(self) -> Dict[str, Any]:
        return asdict(self)
