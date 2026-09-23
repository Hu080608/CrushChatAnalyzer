"""聊天记录导入器。

支持常见的微信聊天导出格式：

* 纯文本（微信 PC 端复制内容、WeChatMsg/PyWxDump 导出的 txt 等）
* CSV / TSV（常见的 ``StrContent, CreateTime, IsSender, NickName`` 列）
* JSON / JSONL（常见的 ``messages`` / ``chat`` / ``data`` 列表）

导入后统一转换为 :class:`~crush_analyzer.models.ChatSession`。
"""
from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import ChatSession, ImportResult, Message, clean_name, parse_dt


class ChatImportError(ValueError):
    """导入聊天记录失败。"""


ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "utf-16")


def read_text_auto(path: Path) -> str:
    """尝试多种编码读取文本文件。"""
    data = Path(path).read_bytes()
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # 最后用 replace，至少不中断导入
    return data.decode("utf-8", errors="replace")


def detect_format(path: Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in (".txt", ".log", ".text"):
        return "txt"
    if suffix in (".csv", ".tsv"):
        return "csv"
    if suffix in (".json", ".jsonl", ".ndjson"):
        return "json"
    # 根据内容猜
    try:
        text = read_text_auto(path)[:4096]
    except OSError:
        return "txt"
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return "json"
    if "," in text.splitlines()[0] if text.splitlines() else False:
        return "csv"
    return "txt"


# ----------------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------------
_SPACE_RE = re.compile(r"\s+")


def _norm_header(value: Any) -> str:
    if value is None:
        return ""
    return _SPACE_RE.sub("", str(value).strip().lower()).replace("_", "").replace("-", "")


def _get_any(row: Dict[str, Any], aliases: Sequence[str], default: Any = "") -> Any:
    lowered = {_norm_header(k): v for k, v in row.items()}
    for alias in aliases:
        key = _norm_header(alias)
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "是", "我", "自己", "me", "self", "out", "sent"}


def _content_to_text(value: Any) -> str:
    """把微信 XML/表情等值转成人类可读文本。"""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value)
    if not text:
        return ""
    # 常见的微信 XML 消息，尽量显示 type 和 title
    if text.lstrip().startswith("<") and "msg" in text[:80].lower():
        try:
            import xml.etree.ElementTree as ET

            root = ET.fromstring(text)
            msg_type = str(root.get("type") or root.findtext(".//type") or "")
            title = root.findtext(".//title") or root.findtext(".//des") or ""
            type_labels = {
                "1": "文本",
                "3": "图片",
                "34": "语音",
                "43": "视频",
                "47": "表情包",
                "49": "文件/链接",
                "50": "音视频通话",
                "10000": "系统消息",
            }
            if msg_type == "1" and title:
                return title
            if msg_type in type_labels:
                label = type_labels[msg_type]
                return f"[{label}] {title}".strip() if title else f"[{label}]"
            if msg_type:
                return f"[消息类型 {msg_type}] {title}".strip()
            if title:
                return title
        except Exception:  # noqa: BLE001 - XML 解析失败时继续原样显示
            pass
    return text


def _dedupe_messages(messages: Iterable[Message]) -> List[Message]:
    seen = set()
    result: List[Message] = []
    for index, msg in enumerate(messages):
        key = (
            msg.sender,
            msg.content,
            msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if msg.timestamp else "",
            index,
        )
        # 完全相同的相邻消息很可能是重复导出，跳过
        if result:
            prev = result[-1]
            if (
                prev.sender == msg.sender
                and prev.content == msg.content
                and (
                    prev.timestamp is None
                    or msg.timestamp is None
                    or prev.timestamp == msg.timestamp
                )
            ):
                continue
        if key not in seen:
            seen.add(key)
            result.append(msg)
    return result


def _infer_self_sender(senders: Sequence[str], self_name: str = "") -> str:
    self_name = clean_name(self_name)
    if self_name:
        for sender in senders:
            if clean_name(sender) == self_name:
                return clean_name(sender)
    for marker in ("我", "自己", "本人", "me", "myself", "self"):
        for sender in senders:
            if clean_name(sender).lower() == marker:
                return clean_name(sender)
    # 只有一个发送者时，无法判断，但也不强行标记
    return ""


def _make_message(
    sender: str,
    content: str,
    timestamp: Any = None,
    is_self: bool = False,
    raw: Optional[Dict[str, Any]] = None,
    index: int = 0,
) -> Message:
    return Message(
        sender=clean_name(sender) or "未知",
        content=_content_to_text(content).strip(),
        timestamp=parse_dt(timestamp),
        is_self=bool(is_self),
        message_id=f"import-{index:06d}",
        raw=raw or {},
    )


# ----------------------------------------------------------------------
# 文本导入
# ----------------------------------------------------------------------
_DATE_PART = r"\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?"
_TIME_PART = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?"
_DT_PATTERN = rf"(?:{_DATE_PART}\s+)?{_TIME_PART}"
_FULL_DT_PATTERN = rf"(?:{_DATE_PART}\s+{_TIME_PART}|{_DATE_PART}|{_TIME_PART})"

_HEADER_PATTERNS = [
    # 单独一行的时间：可能是“时间 / 发送人 / 内容”三行式表头
    re.compile(rf"^(?P<dt>{_FULL_DT_PATTERN})$"),
    # 张三 2023-10-01 12:00:00
    re.compile(rf"^(?P<sender>[^:：]{{1,48}}?)\s+(?P<dt>{_FULL_DT_PATTERN})$"),
    # 2023-10-01 12:00:00 张三
    re.compile(rf"^(?P<dt>{_FULL_DT_PATTERN})\s+(?P<sender>[^:：]{{1,48}}?)$"),
    # [2023-10-01 12:00:00] 张三
    re.compile(rf"^\[(?P<dt>{_FULL_DT_PATTERN})\]\s*(?P<sender>[^:：]{{1,48}})$"),
]

_INLINE_PATTERN = re.compile(r"^(?P<sender>[^:：]{1,48}?)[：:]\s*(?P<content>.+)$")
_TIME_PREFIX_PATTERN = re.compile(rf"^(?P<dt>{_FULL_DT_PATTERN})\s*[|｜\-]?\s*(?P<sender>[^:：]{{1,48}})?[:：]?\s*(?P<content>.*)$")


def import_txt(path: Path, self_name: str = "") -> Tuple[List[Message], List[str]]:
    text = read_text_auto(path)
    lines = text.splitlines()
    warnings: List[str] = []
    messages: List[Message] = []
    pending: Optional[Message] = None
    waiting_for_sender = False
    index = 0

    def flush() -> None:
        nonlocal pending, index, waiting_for_sender
        if pending is None:
            return
        pending.content = pending.content.strip()
        if pending.content:
            messages.append(pending)
            index += 1
        pending = None
        waiting_for_sender = False

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            if pending is not None and pending.content:
                pending.content += "\n"
            continue

        # 两行式表头：先出现时间，下一行是发送人，再下一行才是内容。
        if waiting_for_sender and pending is not None:
            if any(pattern.match(stripped) for pattern in _HEADER_PATTERNS):
                # 下一行又是时间戳，说明这个格式没有独立发送人，放弃等待。
                waiting_for_sender = False
            else:
                pending.sender = stripped
                waiting_for_sender = False
                continue

        matched = False
        for pattern in _HEADER_PATTERNS:
            m = pattern.match(stripped)
            if not m:
                continue
            groups = m.groupdict()
            sender = (groups.get("sender") or "").strip()
            dt = (groups.get("dt") or "").strip()
            if not sender and not dt:
                continue
            flush()
            pending = Message(
                sender=sender or "未知",
                content="",
                timestamp=parse_dt(dt),
                is_self=False,
                message_id=f"txt-{len(messages):06d}",
                raw={"line": stripped},
            )
            if not sender:
                waiting_for_sender = True
            matched = True
            break
        if matched:
            continue

        # 带时间前缀的行内形式：2023-10-01 12:00 张三: 你好
        m = _TIME_PREFIX_PATTERN.match(stripped)
        if m and m.group("sender") and m.group("content"):
            flush()
            pending = Message(
                sender=m.group("sender").strip(),
                content=m.group("content").strip(),
                timestamp=parse_dt(m.group("dt")),
                is_self=False,
                message_id=f"txt-time-{len(messages):06d}",
                raw={"line": stripped},
            )
            continue

        # 纯行内形式：张三: 你好
        m = _INLINE_PATTERN.match(stripped)
        if m:
            sender = m.group("sender").strip()
            content = m.group("content")
            if sender and content:
                flush()
                pending = Message(
                    sender=sender,
                    content=content,
                    timestamp=None,
                    is_self=False,
                    message_id=f"txt-inline-{len(messages):06d}",
                    raw={"line": stripped},
                )
                continue

        # 普通内容，接到当前消息上
        if pending is not None:
            pending.content += ("\n" if pending.content else "") + stripped
        else:
            # 没有识别到发送人时，先当作“未知”消息，避免整段丢失
            pending = Message(
                sender="未知",
                content=stripped,
                timestamp=None,
                is_self=False,
                message_id=f"txt-unknown-{len(messages):06d}",
                raw={"line": stripped},
            )

    flush()
    messages = _dedupe_messages(messages)
    if not messages:
        raise ChatImportError("没有从文本中解析出消息，请检查导出格式。")
    senders = list(dict.fromkeys(m.sender for m in messages if m.sender))
    if not self_name and len(senders) > 2:
        warnings.append(f"检测到 {len(senders)} 个发送者，建议在界面中指定“我是谁”。")
    self_sender = _infer_self_sender(senders, self_name)
    for msg in messages:
        msg.is_self = bool(self_sender) and msg.sender == self_sender
    if not self_sender:
        warnings.append("未指定“我是谁”，将按发送者原样展示；可在界面中重新指定。")
    return messages, warnings


# ----------------------------------------------------------------------
# CSV / TSV 导入
# ----------------------------------------------------------------------
SENDER_ALIASES = [
    "sender",
    "from",
    "nickname",
    "nickName",
    "sendername",
    "sender_name",
    "fromuser",
    "from_user",
    "username",
    "user_name",
    "talker",
    "talkername",
    "displayname",
    "remark",
    "发送人",
    "发送者",
    "昵称",
    "联系人",
    "对方",
    "用户",
]
CONTENT_ALIASES = [
    "content",
    "message",
    "msg",
    "strcontent",
    "text",
    "body",
    "messagecontent",
    "消息",
    "内容",
    "聊天内容",
    "文本",
    "Msg",
]
TIME_ALIASES = [
    "time",
    "timestamp",
    "datetime",
    "date",
    "createtime",
    "create_time",
    "strtime",
    "sendtime",
    "send_time",
    "msgtime",
    "时间",
    "日期",
    "发送时间",
    "消息时间",
]
IS_SELF_ALIASES = [
    "issender",
    "is_sender",
    "is_self",
    "fromme",
    "from_me",
    "issend",
    "is_send",
    "direction",
    "是否我发送",
    "是否本人",
    "发送方",
]


def _sniff_csv(text: str) -> Tuple[str, Optional[List[str]]]:
    sample_lines = text.splitlines()[:20]
    sample = "\n".join(sample_lines)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        lines = [ln for ln in sample_lines if ln.strip()]
        delimiter = "\t" if lines and lines[0].count("\t") > lines[0].count(",") else ","
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    first = next(reader, [])
    header = [c.strip() for c in first] if first else None
    return delimiter, header


def import_csv(path: Path, self_name: str = "") -> Tuple[List[Message], List[str]]:
    text = read_text_auto(path)
    delimiter, header = _sniff_csv(text)
    rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
    if not rows:
        raise ChatImportError("CSV 文件为空。")
    warnings: List[str] = []

    # 判断是否有表头
    header_norm = [_norm_header(h) for h in rows[0]]
    alias_set = {_norm_header(a) for a in SENDER_ALIASES + CONTENT_ALIASES + TIME_ALIASES + IS_SELF_ALIASES}
    has_header = any(h in alias_set for h in header_norm)
    if not has_header:
        # 无表头时按常见列序推断：时间、发送人、内容、是否我
        warnings.append("CSV 未检测到表头，已按“时间/发送人/内容/是否我”尝试解析。")
        header = ["time", "sender", "content", "is_self"]
        data_rows = rows
    else:
        header = [str(c).strip() for c in rows[0]]
        data_rows = rows[1:]

    messages: List[Message] = []
    for index, row in enumerate(data_rows):
        if not any(str(c).strip() for c in row):
            continue
        record: Dict[str, Any] = {}
        for col_index, value in enumerate(row):
            key = header[col_index] if col_index < len(header) else f"col_{col_index}"
            record[key] = value
        sender = clean_name(_get_any(record, SENDER_ALIASES, ""))
        content = _content_to_text(_get_any(record, CONTENT_ALIASES, "")).strip()
        timestamp = _get_any(record, TIME_ALIASES, "")
        is_self_value = _get_any(record, IS_SELF_ALIASES, None)
        is_self = _as_bool(is_self_value) if is_self_value is not None else False
        if not content:
            continue
        if not sender:
            sender = "我" if is_self else "对方"
        messages.append(
            _make_message(sender, content, timestamp, is_self, raw=record, index=index)
        )

    messages = _dedupe_messages(messages)
    if not messages:
        raise ChatImportError("CSV 中没有解析出消息，请检查列名或导出格式。")
    senders = list(dict.fromkeys(m.sender for m in messages if m.sender))
    self_sender = _infer_self_sender(senders, self_name)
    if self_sender:
        for msg in messages:
            msg.is_self = msg.sender == self_sender
    elif any(m.is_self for m in messages):
        # CSV 自身的 IsSender 字段可以信任
        self_name_guess = next((m.sender for m in messages if m.is_self), "")
        self_sender = self_name_guess or ""
        if self_sender:
            for msg in messages:
                if msg.sender == self_sender:
                    msg.is_self = True
    else:
        warnings.append("未指定“我是谁”，可在界面中重新指定。")
    return messages, warnings


# ----------------------------------------------------------------------
# JSON / JSONL 导入
# ----------------------------------------------------------------------
JSON_LIST_KEYS = (
    "messages",
    "messageList",
    "message_list",
    "msgList",
    "msg_list",
    "chat",
    "chatList",
    "records",
    "recordList",
    "items",
    "list",
    "data",
    "msgs",
    "MsgList",
    "message_list",
)


def _first_list(value: Any) -> Optional[List[Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in JSON_LIST_KEYS:
            if key in value:
                found = _first_list(value[key])
                if found is not None:
                    return found
        for child in value.values():
            if isinstance(child, list) and child and isinstance(child[0], (dict, list)):
                return child
    return None


def _extract_json_records(obj: Any) -> List[Dict[str, Any]]:
    """从各种嵌套结构中提取消息字典列表。"""
    if isinstance(obj, list):
        records: List[Dict[str, Any]] = []
        for item in obj:
            records.extend(_extract_json_records(item))
        return records
    if not isinstance(obj, dict):
        return []
    # 当前对象自身看起来像一条消息
    message_keys = {_norm_header(k) for k in obj.keys()}
    if any(_norm_header(a) in message_keys for a in CONTENT_ALIASES):
        return [obj]
    found = _first_list(obj)
    if found is not None:
        records = []
        for item in found:
            if isinstance(item, dict):
                records.extend(_extract_json_records(item))
            elif isinstance(item, list):
                records.extend(_extract_json_records(item))
        return records
    # 结构是 {日期: {发送人: 内容}} 时暂时难以表达，忽略。
    return []


def import_json(path: Path, self_name: str = "") -> Tuple[List[Message], List[str]]:
    text = read_text_auto(path)
    warnings: List[str] = []
    records: List[Dict[str, Any]] = []
    try:
        data = json.loads(text)
        records = _extract_json_records(data)
    except json.JSONDecodeError:
        # JSONL：逐行解析
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.extend(_extract_json_records(item))

    messages: List[Message] = []
    for index, record in enumerate(records):
        # 有些导出把消息嵌套在 message/msg 字段里，只保留一层即可
        source = record
        for nested_key in ("message", "msg", "Message", "Msg"):
            if nested_key in record and isinstance(record[nested_key], dict):
                merged = dict(record)
                merged.update(record[nested_key])
                source = merged
                break
        sender = clean_name(_get_any(source, SENDER_ALIASES, ""))
        content = _content_to_text(_get_any(source, CONTENT_ALIASES, "")).strip()
        timestamp = _get_any(source, TIME_ALIASES, "")
        is_self_value = _get_any(source, IS_SELF_ALIASES, None)
        is_self = _as_bool(is_self_value) if is_self_value is not None else False
        if not content:
            continue
        if not sender:
            sender = "我" if is_self else "对方"
        messages.append(_make_message(sender, content, timestamp, is_self, raw=source, index=index))

    messages = _dedupe_messages(messages)
    if not messages:
        raise ChatImportError(
            "JSON 中没有找到消息列表。支持 {messages:[...]}、[{...}]、{chat:[...]} 等结构。"
        )
    senders = list(dict.fromkeys(m.sender for m in messages if m.sender))
    self_sender = _infer_self_sender(senders, self_name)
    if self_sender:
        for msg in messages:
            msg.is_self = msg.sender == self_sender
    elif any(m.is_self for m in messages):
        self_sender = next((m.sender for m in messages if m.is_self), "")
        if self_sender:
            for msg in messages:
                msg.is_self = msg.sender == self_sender
    else:
        warnings.append("未指定“我是谁”，可在界面中重新指定。")
    return messages, warnings


# ----------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------
def make_session(
    messages: List[Message],
    name: str = "导入的会话",
    source: str = "",
    self_name: str = "",
) -> ChatSession:
    senders = list(dict.fromkeys(m.sender for m in messages if m.sender))
    self_sender = ""
    if self_name:
        self_sender = _infer_self_sender(senders, self_name)
    if not self_sender:
        self_sender = next((m.sender for m in messages if m.is_self), "")
    other_sender = next((s for s in senders if s != self_sender), "")
    session = ChatSession(
        name=clean_name(name) or "导入的会话",
        platform="wechat",
        source=source,
        self_sender=clean_name(self_sender),
        other_sender=clean_name(other_sender),
        messages=list(messages),
    )
    session.normalize_roles(self_sender) if self_sender else None
    return session


def import_file(
    path: str | Path,
    self_name: str = "",
    session_name: str = "",
    fmt: Optional[str] = None,
) -> ImportResult:
    """导入一个聊天记录文件。

    Parameters
    ----------
    path:
        文件路径。
    self_name:
        你在聊天中的昵称，用于区分“我”和“对方”。
    session_name:
        可选，导入后在界面显示的会话名。
    fmt:
        强制指定 ``txt`` / ``csv`` / ``json``。
    """
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ChatImportError(f"文件不存在：{file_path}")
    if file_path.stat().st_size == 0:
        raise ChatImportError("文件为空。")

    fmt = (fmt or detect_format(file_path)).lower()
    if fmt == "txt":
        messages, warnings = import_txt(file_path, self_name)
    elif fmt == "csv":
        messages, warnings = import_csv(file_path, self_name)
    elif fmt == "json":
        messages, warnings = import_json(file_path, self_name)
    else:
        raise ChatImportError(f"不支持的格式：{fmt}")

    name = session_name.strip() or file_path.stem
    session = make_session(messages, name=name, source=str(file_path), self_name=self_name)
    return ImportResult(session=session, warnings=warnings, detected_format=fmt)
