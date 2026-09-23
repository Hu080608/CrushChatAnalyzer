"""SQLite 持久化。

项目自身不依赖 ORM，方便打包成 exe。
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable, List, Optional

from .config import app_home
from .models import AnalysisRecord, ChatSession, Message, format_dt, parse_dt


DEFAULT_DB_NAME = "crush_chat.db"


class Database:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else app_home() / DEFAULT_DB_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._init_schema()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._conn()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'wechat',
                    source TEXT DEFAULT '',
                    self_sender TEXT DEFAULT '',
                    other_sender TEXT DEFAULT '',
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    meta TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sender TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    timestamp TEXT DEFAULT '',
                    is_self INTEGER DEFAULT 0,
                    raw TEXT DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dedupe
                    ON messages(session_id, message_id);
                CREATE INDEX IF NOT EXISTS idx_messages_session_time
                    ON messages(session_id, id);

                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    created_at TEXT DEFAULT '',
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_analyses_session
                    ON analyses(session_id, id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT ''
                );
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # 会话和消息
    # ------------------------------------------------------------------
    def save_session(self, session: ChatSession, replace_messages: bool = True) -> None:
        """保存会话和消息。默认覆盖该会话全部消息。"""
        with self._lock:
            conn = self._conn()
            session.updated_at = datetime.now()
            conn.execute(
                """
                INSERT INTO sessions
                    (id, name, platform, source, self_sender, other_sender, created_at, updated_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    platform=excluded.platform,
                    source=excluded.source,
                    self_sender=excluded.self_sender,
                    other_sender=excluded.other_sender,
                    updated_at=excluded.updated_at,
                    meta=excluded.meta
                """,
                session.to_row(),
            )
            if replace_messages:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session.id,))
                for msg in session.messages:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO messages
                            (message_id, session_id, sender, content, timestamp, is_self, raw)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        msg.to_row(session.id),
                    )
            conn.commit()

    def append_messages(self, session_id: str, messages: Iterable[Message]) -> int:
        inserted = 0
        with self._lock:
            conn = self._conn()
            for msg in messages:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO messages
                        (message_id, session_id, sender, content, timestamp, is_self, raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    msg.to_row(session_id),
                )
                inserted += cur.rowcount
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (format_dt(datetime.now()), session_id),
            )
            conn.commit()
        return inserted

    def list_sessions(self) -> List[ChatSession]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                """
                SELECT s.*, COUNT(m.id) AS message_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.created_at DESC
                """
            ).fetchall()
        result = []
        for row in rows:
            session = ChatSession.from_row(row, [])
            session.meta["message_count"] = row["message_count"]
            result.append(session)
        return result

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        with self._lock:
            conn = self._conn()
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            msg_rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
            ).fetchall()
        return ChatSession.from_row(row, [Message.from_row(r) for r in msg_rows])

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

    def message_count(self, session_id: str) -> int:
        with self._lock:
            conn = self._conn()
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------
    # 分析记录
    # ------------------------------------------------------------------
    def add_analysis(
        self,
        session_id: str,
        kind: str,
        content: str,
        model: str = "",
        created_at: Optional[datetime] = None,
    ) -> int:
        with self._lock:
            conn = self._conn()
            cur = conn.execute(
                """
                INSERT INTO analyses(session_id, kind, model, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, kind, model, content, format_dt(created_at or datetime.now())),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_latest_analysis(self, session_id: str, kind: Optional[str] = None) -> Optional[AnalysisRecord]:
        with self._lock:
            conn = self._conn()
            if kind:
                row = conn.execute(
                    "SELECT * FROM analyses WHERE session_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
                    (session_id, kind),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM analyses WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
        if row is None:
            return None
        return AnalysisRecord(
            id=row["id"],
            session_id=row["session_id"],
            kind=row["kind"],
            model=row["model"],
            content=row["content"],
            created_at=parse_dt(row["created_at"]),
        )

    # ------------------------------------------------------------------
    # 设置（键值对，供 GUI 保存自动回复等轻量状态）
    # ------------------------------------------------------------------
    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            conn = self._conn()
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
