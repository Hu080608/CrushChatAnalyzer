"""自动回复引擎。

在后台线程轮询微信会话的新消息，调用 DeepSeek 生成回复，并通过 wxauto 发送。
默认 ``dry_run=True``，也就是只生成不发送，方便用户先观察效果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import AppConfig
from .deepseek import DeepSeekClient, DeepSeekError
from .logs import get_logger
from .media_ai import enrich_media_messages
from .models import ChatSession, Message
from .storage import Database
from .wechat import WeChatError, create_backend


logger = get_logger("auto_reply")


@dataclass
class AutoReplyEvent:
    kind: str  # status / incoming / generated / sent / error / stopped
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=datetime.now)


EventCallback = Callable[[AutoReplyEvent], None]


def _message_fingerprint(msg: Message) -> str:
    if msg.message_id:
        return f"id:{msg.message_id}"
    time_part = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if msg.timestamp else ""
    return f"t:{time_part}|{msg.sender}|{msg.content[:80]}"


def _sessions_to_chat_session(
    chat: str,
    messages: List[Message],
    self_name: str = "",
    other_name: str = "",
) -> ChatSession:
    """把微信当前会话消息包装成 ChatSession。"""
    history = messages[-120:]
    # 尽量推断“我是谁”
    self_sender = self_name.strip()
    if not self_sender:
        for marker in ("我", "自己", "本人", "Self", "self", "me", "Me"):
            if any(m.sender == marker for m in history):
                self_sender = marker
                break
    if not self_sender:
        # 无法判断时，默认把“对方”标记为第一个非空发送者，self 留空；
        # 引擎会在 start() 前要求用户先设置昵称。
        pass
    for msg in history:
        if self_sender:
            msg.is_self = msg.sender == self_sender
    other_sender = other_name.strip()
    if not other_sender:
        other_sender = next((m.sender for m in history if m.sender and m.sender != self_sender), chat)
    return ChatSession(
        name=chat,
        platform="wechat",
        source=chat,
        self_sender=self_sender,
        other_sender=other_sender,
        messages=list(history),
    )


class AutoReplyService:
    def __init__(
        self,
        config: AppConfig,
        db: Optional[Database] = None,
        backend: Any = None,
        callback: Optional[EventCallback] = None,
        client_factory: Optional[Callable[[AppConfig], DeepSeekClient]] = None,
    ):
        self.config = config
        self.db = db
        self.backend = backend or create_backend()
        self.callback = callback
        self.client_factory = client_factory or (lambda cfg: DeepSeekClient(cfg))
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._last_sent_at = datetime.min
        self._sent_in_window: List[datetime] = []
        self._media_cache: Dict[str, str] = {}
        self._pending_incoming: List[Message] = []
        self._pending_last_at: Optional[datetime] = None
        self.chat = ""
        self.session_id: Optional[str] = None
        self.error: str = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _emit(self, kind: str, message: str, **data: Any) -> None:
        if kind in ("error", "stopped", "sent", "generated", "incoming"):
            logger.info("auto_reply event=%s message=%s", kind, message)
        else:
            logger.debug("auto_reply event=%s message=%s", kind, message)
        event = AutoReplyEvent(kind=kind, message=message, data=data)
        if self.callback:
            try:
                self.callback(event)
            except Exception:  # noqa: BLE001 - UI 回调不应影响回复线程
                pass

    def start(self, chat: str, session_id: Optional[str] = None) -> None:
        if self.running:
            return
        chat = (chat or "").strip()
        if not chat:
            raise ValueError("请先选择要自动回复的微信联系人。")
        if not (self.config.api_key or "").strip():
            raise ValueError("请先在设置中填写 DeepSeek API Key。")
        if not (self.config.wechat_self_name or "").strip():
            # 仍允许尝试，但提醒识别可能不准确
            self._emit("status", "未设置“我的微信昵称”，自动回复可能识别不准，建议先到设置中填写。")
        self.chat = chat
        self.session_id = session_id
        self.error = ""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="crush-auto-reply", daemon=True)
        self._thread.start()
        self._emit("status", f"自动回复已启动：{chat}")

    def stop(self, wait: bool = False) -> None:
        was_running = self.running
        self._stop_event.set()
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if was_running:
            self._emit("stopped", "自动回复已停止。")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def _run(self) -> None:
        known: Dict[str, datetime] = {}
        # 第一轮把当前消息标记为已读，避免启动后回复旧消息
        try:
            initial = self.backend.fetch_messages(self.chat, limit=80)
            for msg in initial:
                known[_message_fingerprint(msg)] = datetime.now()
            self._emit("status", f"已加载 {len(initial)} 条历史消息，开始监听新消息。")
        except Exception as exc:  # noqa: BLE001
            self._emit("error", f"读取微信消息失败：{exc}")
            self._emit("stopped", "自动回复未启动成功。")
            return

        client = self.client_factory(self.config)
        while not self._stop_event.is_set():
            try:
                self._tick(client, known)
            except WeChatError as exc:
                self._emit("error", str(exc))
                time.sleep(max(3, int(self.config.auto_reply_poll_interval or 5)))
            except DeepSeekError as exc:
                self._emit("error", exc.user_message)
                time.sleep(max(3, int(self.config.auto_reply_poll_interval or 5)))
            except Exception as exc:  # noqa: BLE001
                self._emit("error", f"自动回复运行异常：{exc}")
                time.sleep(max(3, int(self.config.auto_reply_poll_interval or 5)))

            # 可随时停止
            for _ in range(max(1, int(self.config.auto_reply_poll_interval or 5)) * 10):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

        self._emit("stopped", "自动回复线程已退出。")

    def _collect_new_incoming(self, known: Dict[str, datetime]) -> tuple[List[Message], List[Message]]:
        """拉取消息，并把新来的非自己消息标记为已读。"""
        messages = self.backend.fetch_messages(self.chat, limit=80)
        if not messages:
            return [], []
        enrich_media_messages(messages, self.backend, self.config, cache=self._media_cache)
        new_incoming: List[Message] = []
        self_name = (self.config.wechat_self_name or "").strip()
        for msg in messages:
            fingerprint = _message_fingerprint(msg)
            if fingerprint in known:
                continue
            known[fingerprint] = datetime.now()
            if msg.is_self:
                continue
            if self_name and msg.sender.strip() == self_name:
                continue
            new_incoming.append(msg)
        return messages, new_incoming

    def _tick(self, client: DeepSeekClient, known: Dict[str, datetime]) -> None:
        messages, new_incoming = self._collect_new_incoming(known)
        self_name = (self.config.wechat_self_name or "").strip()

        if new_incoming:
            self._pending_incoming.extend(new_incoming)
            self._pending_last_at = datetime.now()
            latest = new_incoming[-1]
            combined_new = " / ".join((m.content or "").strip() for m in new_incoming if (m.content or "").strip())
            self._emit("incoming", f"{latest.sender}: {combined_new[:120]}", messages=[m.content for m in new_incoming])

        if not self._pending_incoming:
            return

        quiet_seconds = max(2, int(self.config.auto_reply_quiet_seconds or 5))
        now = datetime.now()
        if self._pending_last_at and (now - self._pending_last_at).total_seconds() < quiet_seconds:
            self._emit("status", f"等待对方说完（{quiet_seconds} 秒内可能还有消息）…")
            return

        batch = self._pending_incoming
        self._pending_incoming = []
        self._pending_last_at = None
        latest = batch[-1]
        combined_text = " / ".join((m.content or "").strip() for m in batch if (m.content or "").strip())
        if not combined_text:
            return

        skip_keywords = [k.strip() for k in (self.config.auto_reply_skip_keywords or "").split(",") if k.strip()]
        if any(keyword and keyword in combined_text for keyword in skip_keywords):
            self._emit("status", "命中跳过关键词，本条不自动回复。")
            return

        now = datetime.now()
        self._sent_in_window = [t for t in self._sent_in_window if now - t < timedelta(minutes=1)]
        max_per_min = max(1, int(self.config.auto_reply_max_per_minute or 6))
        if len(self._sent_in_window) >= max_per_min:
            self._emit("status", "已达到每分钟自动回复上限，跳过本条。")
            return

        session = _sessions_to_chat_session(
            self.chat,
            messages,
            self_name=self_name,
            other_name=latest.sender,
        )
        if session.self_sender:
            latest.is_self = latest.sender == session.self_sender
        analysis_context = ""
        if self.db is not None and self.session_id:
            try:
                record = (
                    self.db.get_latest_analysis(self.session_id, "deepseek")
                    or self.db.get_latest_analysis(self.session_id, "local")
                )
                if record is not None:
                    analysis_context = (record.content or "").strip()
            except Exception:
                analysis_context = ""
        if analysis_context:
            self._emit("status", "已参考最近一次 AI 分析结论。")
        else:
            self._emit("status", "未找到 AI 分析结论，仅根据聊天记录回复；建议先做 AI 分析。")
        reply = client.auto_reply(
            session,
            incoming=latest,
            persona=self.config.system_persona,
            style=self.config.auto_reply_style,
            analysis=analysis_context,
        )
        reply = (reply or "").strip()
        if not reply:
            return

        usage_info = getattr(client, "last_usage_info", None)
        if usage_info is not None and getattr(usage_info, "total_tokens", 0):
            self._emit("usage", usage_info.format_detail(), usage_info=usage_info)

        # 生成期间如果对方又发来消息，先不发送，合并到下一轮，避免回复不完整。
        _latest_messages, newer = self._collect_new_incoming(known)
        if newer:
            self._pending_incoming.extend(newer)
            self._pending_last_at = datetime.now()
            self._emit("status", "回复生成期间对方又发来消息，已合并到下一轮回复。")
            return

        self._emit("generated", f"AI 回复：{reply}", reply=reply)
        if self.config.auto_reply_dry_run:
            self._emit("status", "当前为演练模式，仅生成不发送。")
            return

        self.backend.send_message(self.chat, reply)
        self._sent_in_window.append(datetime.now())
        self._last_sent_at = datetime.now()
        self._emit("sent", f"已发送：{reply}", reply=reply)

        # 发送后立即重新拉取一次，把自己的回复标记为已知，避免被当成新消息重复回复。
        try:
            for sent in self.backend.fetch_messages(self.chat, limit=30):
                known[_message_fingerprint(sent)] = datetime.now()
        except Exception:  # noqa: BLE001 - 拉取失败不影响已发送结果
            pass
