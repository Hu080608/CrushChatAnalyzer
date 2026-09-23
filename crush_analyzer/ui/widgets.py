"""可复用 Tkinter 控件。"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Iterable, List, Optional
import webbrowser

from ..models import ChatSession, Message


class ChatTranscript(ttk.Frame):
    """聊天记录展示区。

    用 Text 控件模拟聊天气泡：自己靠右、对方靠左，支持复制和关键词搜索。
    """

    def __init__(self, master: tk.Misc, **kwargs):
        super().__init__(master, **kwargs)
        self.text = tk.Text(
            self,
            wrap="word",
            padx=14,
            pady=10,
            relief="flat",
            borderwidth=0,
            state="disabled",
            font=("Microsoft YaHei UI", 10),
            spacing1=2,
            spacing2=4,
            spacing3=8,
            cursor="arrow",
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self._configure_tags()
        self._session: Optional[ChatSession] = None
        self._visible_messages: List[Message] = []
        self._search_matches: List[tuple[str, str]] = []
        self._search_index = -1

    def _configure_tags(self) -> None:
        self.text.tag_configure("self_name", foreground="#1d4ed8", justify="right", font=("Microsoft YaHei UI", 9, "bold"))
        self.text.tag_configure(
            "self_body",
            foreground="#1e3a8a",
            background="#eef2ff",
            justify="right",
            lmargin1=60,
            lmargin2=60,
            rmargin=10,
            spacing1=3,
            spacing3=6,
        )
        self.text.tag_configure("other_name", foreground="#047857", justify="left", font=("Microsoft YaHei UI", 9, "bold"))
        self.text.tag_configure(
            "other_body",
            foreground="#064e3b",
            background="#ecfdf5",
            justify="left",
            lmargin1=10,
            lmargin2=10,
            rmargin=60,
            spacing1=3,
            spacing3=6,
        )
        self.text.tag_configure("unknown_name", foreground="#616161", justify="left", font=("Microsoft YaHei UI", 9, "bold"))
        self.text.tag_configure("unknown_body", foreground="#424242", justify="left", lmargin1=10, lmargin2=10)
        self.text.tag_configure("meta", foreground="#9e9e9e", font=("Microsoft YaHei UI", 8))
        self.text.tag_configure("divider", foreground="#e0e0e0")
        self.text.tag_configure("highlight", background="#fff59d")
        self.text.tag_configure("highlight_current", background="#ffb74d")

    @property
    def session(self) -> Optional[ChatSession]:
        return self._session

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._session = None
        self._visible_messages = []

    def set_session(self, session: Optional[ChatSession], max_messages: int = 5000) -> None:
        self.clear()
        self._session = session
        if session is None:
            self._insert_placeholder("请选择左侧会话，或点击“导入聊天记录”。")
            return
        if not session.messages:
            self._insert_placeholder("这个会话还没有消息。")
            return
        messages = session.messages
        truncated = 0
        if len(messages) > max_messages:
            truncated = len(messages) - max_messages
            messages = messages[-max_messages:]
        self._visible_messages = list(messages)
        self.text.configure(state="normal")
        if truncated:
            self.text.insert("end", f"（已隐藏较早的 {truncated} 条消息，仅显示最近 {max_messages} 条）\n\n", "meta")
        for msg in messages:
            self._insert_message(msg)
        self.text.configure(state="disabled")
        self.text.see("end")

    def _insert_placeholder(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", f"\n{text}\n", "meta")
        self.text.configure(state="disabled")

    def _role(self, msg: Message) -> str:
        session = self._session
        if msg.is_self:
            return "self"
        if session and session.self_sender and msg.sender == session.self_sender:
            return "self"
        if session and session.other_sender and msg.sender == session.other_sender:
            return "other"
        if session:
            # 有明确“我”时，其他人一律按对方展示
            if session.self_sender:
                return "other"
            senders = [s for s in session.senders if s]
            if len(senders) <= 2:
                return "other"
        return "unknown"

    def _insert_message(self, msg: Message) -> None:
        role = self._role(msg)
        name = "我" if role == "self" else (msg.sender or "对方")
        time_text = f"  {msg.timestamp:%m-%d %H:%M}" if msg.timestamp else ""
        self.text.insert("end", f"{name}{time_text}\n", f"{role}_name")
        body = (msg.content or "").strip() or "[空消息]"
        self.text.insert("end", f"{body}\n\n", f"{role}_body")

    def append_system_note(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", f"— {text} —\n\n", "meta")
        self.text.configure(state="disabled")
        self.text.see("end")

    def highlight(self, keyword: str) -> int:
        self.text.tag_remove("highlight", "1.0", "end")
        self.text.tag_remove("highlight_current", "1.0", "end")
        self._search_matches = []
        self._search_index = -1
        keyword = (keyword or "").strip()
        if not keyword:
            return 0
        count = tk.IntVar()
        start = "1.0"
        while True:
            pos = self.text.search(keyword, start, stopindex="end", nocase=True, count=count)
            if not pos:
                break
            end = f"{pos}+{count.get()}c"
            self._search_matches.append((pos, end))
            self.text.tag_add("highlight", pos, end)
            start = end
            if len(self._search_matches) > 2000:
                break
        if self._search_matches:
            self._search_index = 0
            self._mark_current_match()
        return len(self._search_matches)

    def _mark_current_match(self) -> None:
        self.text.tag_remove("highlight_current", "1.0", "end")
        if 0 <= self._search_index < len(self._search_matches):
            start, end = self._search_matches[self._search_index]
            self.text.tag_add("highlight_current", start, end)
            self.text.see(start)

    def goto_match(self, delta: int) -> tuple[int, int]:
        if not self._search_matches:
            return 0, 0
        self._search_index = (self._search_index + delta) % len(self._search_matches)
        self._mark_current_match()
        return self._search_index + 1, len(self._search_matches)

    def clear_search_highlight(self) -> None:
        self.text.tag_remove("highlight", "1.0", "end")
        self.text.tag_remove("highlight_current", "1.0", "end")
        self._search_matches = []
        self._search_index = -1


class LabeledEntry(ttk.Frame):
    def __init__(self, master: tk.Misc, label: str, textvariable: Optional[tk.Variable] = None, width: int = 30, show: str = ""):
        super().__init__(master)
        self.label = ttk.Label(self, text=label, width=14, anchor="e")
        self.label.pack(side="left", padx=(0, 6))
        self.entry = ttk.Entry(self, textvariable=textvariable, width=width, show=show)
        self.entry.pack(side="left", fill="x", expand=True)

    def get(self) -> str:
        return self.entry.get()

    def set(self, value: str) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, value)


class ScrollableFrame(ttk.Frame):
    """可滚动 Frame。

    修复了鼠标放在内部子控件上时滚轮无效的问题：
    使用全局滚轮绑定，再根据鼠标指针位置判断是否属于当前滚动区域。
    """

    def __init__(self, master: tk.Misc, **kwargs):
        super().__init__(master, **kwargs)
        self._destroyed = False
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # add="+"：允许多个 ScrollableFrame 同时注册，各自判断指针是否在自己内部。
        try:
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        except Exception:
            self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event) -> None:
        if event.widget is self:
            self._destroyed = True

    def _pointer_inside(self) -> bool:
        if self._destroyed:
            return False
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
        except Exception:
            return False
        while widget is not None:
            if widget is self or widget is self.canvas or widget is self.inner:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_mousewheel(self, event) -> Optional[str]:
        if not self._pointer_inside():
            return None
        delta = int(getattr(event, "delta", 0) or 0)
        if not delta:
            return None
        # Windows 的滚轮 delta 通常是 120 的倍数；触控板可能更小。
        if abs(delta) >= 120:
            steps = -1 * int(delta / 120)
        else:
            steps = -1 if delta > 0 else 1
        self.canvas.yview_scroll(steps, "units")
        return "break"

class CheckMarkButton(ttk.Frame):
    """自定义勾选按钮：选中显示 ✓，未选中显示 □。

    ttk.Checkbutton 在部分 Windows 主题下选中状态会显示成“x”，
    这个控件可以保证 0 基础用户看到明确的 √。
    """

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        variable: tk.Variable,
        background: str = "#f3f4f6",
        **kwargs: Any,
    ):
        super().__init__(master, **kwargs)
        self.variable = variable
        self.label_text = text
        self.background = background
        self.button = tk.Checkbutton(
            self,
            variable=variable,
            command=self._sync,
            indicatoron=False,
            anchor="w",
            relief="flat",
            bd=0,
            padx=9,
            pady=5,
            cursor="hand2",
            activebackground="#e0e7ff",
            background=background,
            highlightthickness=0,
        )
        self.button.pack(fill="x")
        try:
            self.variable.trace_add("write", lambda *_a: self._sync())
        except Exception:
            pass
        self._sync()

    def _sync(self) -> None:
        try:
            checked = bool(self.variable.get())
        except Exception:
            checked = False
        self.button.configure(
            text=f"{'✓' if checked else '□'} {self.label_text}",
            background="#e0e7ff" if checked else self.background,
            relief="sunken" if checked else "flat",
        )


class MarkdownText(ttk.Frame):
    """带基础 Markdown 渲染的只读文本区。

    支持标题、粗体、斜体、行内代码、代码块、列表、引用、链接和简单表格。
    不依赖第三方 markdown 库，适合打包。
    """

    INLINE_RE = re.compile(
        r"(\*\*.+?\*\*|__.+?__|`[^`]+`|\*[^*\n]+?\*|_[^_\n]+?_|\[[^\]]+\]\([^)]+\))"
    )
    HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
    BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
    NUMBER_RE = re.compile(r"^(\d+)[.)、]\s+(.*)$")

    def __init__(self, master: tk.Misc, **kwargs):
        super().__init__(master, **kwargs)
        self.text = tk.Text(
            self,
            wrap="word",
            padx=16,
            pady=14,
            relief="flat",
            borderwidth=0,
            state="disabled",
            font=("Microsoft YaHei UI", 10),
            spacing1=2,
            spacing2=4,
            spacing3=4,
            cursor="arrow",
            background="#ffffff",
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self._raw = ""
        self._link_urls: Dict[str, str] = {}
        self._link_index = 0
        self._configure_tags()

    def _configure_tags(self) -> None:
        self.text.tag_configure("md_h1", font=("Microsoft YaHei UI", 15, "bold"), foreground="#111827", spacing1=10, spacing3=6)
        self.text.tag_configure("md_h2", font=("Microsoft YaHei UI", 13, "bold"), foreground="#312e81", spacing1=12, spacing3=5)
        self.text.tag_configure("md_h3", font=("Microsoft YaHei UI", 11, "bold"), foreground="#4f46e5", spacing1=9, spacing3=4)
        self.text.tag_configure("md_bold", font=("Microsoft YaHei UI", 10, "bold"), foreground="#111827")
        self.text.tag_configure("md_italic", font=("Microsoft YaHei UI", 10, "italic"), foreground="#374151")
        self.text.tag_configure("md_code", font=("Consolas", 10), background="#f3f4f6", foreground="#be123c")
        self.text.tag_configure("md_code_block", font=("Consolas", 10), background="#f8fafc", foreground="#334155", lmargin1=18, lmargin2=18, spacing1=3, spacing3=3)
        self.text.tag_configure("md_bullet", lmargin1=16, lmargin2=34, spacing1=2)
        self.text.tag_configure("md_number", lmargin1=16, lmargin2=34, spacing1=2)
        self.text.tag_configure("md_quote", foreground="#4b5563", lmargin1=18, lmargin2=18, spacing1=4, spacing3=4)
        self.text.tag_configure("md_hr", foreground="#cbd5e1", spacing1=6, spacing3=6)
        self.text.tag_configure("md_table", font=("Consolas", 10), background="#f8fafc", foreground="#334155", lmargin1=12, lmargin2=12)
        self.text.tag_configure("md_link", foreground="#2563eb", underline=True, font=("Microsoft YaHei UI", 10))

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._raw = ""
        self._link_urls.clear()
        self._link_index = 0

    def render(self, markdown: str) -> None:
        self.clear()
        self._raw = markdown or ""
        self.text.configure(state="normal")
        in_code = False
        code_lines: List[str] = []
        for raw_line in self._raw.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if stripped.startswith("```"):
                if in_code:
                    self._insert_code_block(code_lines)
                    code_lines = []
                    in_code = False
                else:
                    in_code = True
                    code_lines = []
                continue
            if in_code:
                code_lines.append(line)
                continue

            if not stripped:
                self.text.insert("end", "\n")
                continue

            if re.fullmatch(r"[-*_]{3,}", stripped):
                self.text.insert("end", "─" * 44 + "\n", "md_hr")
                continue

            heading = self.HEADING_RE.match(stripped)
            if heading:
                level = len(heading.group(1))
                tag = "md_h1" if level == 1 else ("md_h2" if level == 2 else "md_h3")
                self._insert_inline(heading.group(2), tag)
                self.text.insert("end", "\n")
                continue

            bullet = self.BULLET_RE.match(stripped)
            if bullet:
                self.text.insert("end", "  • ", "md_bullet")
                self._insert_inline(bullet.group(1), "md_bullet")
                self.text.insert("end", "\n")
                continue

            number = self.NUMBER_RE.match(stripped)
            if number:
                self.text.insert("end", f"  {number.group(1)}. ", "md_number")
                self._insert_inline(number.group(2), "md_number")
                self.text.insert("end", "\n")
                continue

            if stripped.startswith(">"):
                self.text.insert("end", "│ ", "md_quote")
                self._insert_inline(stripped[1:].strip(), "md_quote")
                self.text.insert("end", "\n")
                continue

            if stripped.count("|") >= 2:
                if re.fullmatch(r"\|?[\s:|-]+\|?", stripped):
                    self.text.insert("end", "─" * 44 + "\n", "md_hr")
                else:
                    self.text.insert("end", line + "\n", "md_table")
                continue

            self._insert_inline(line, None)
            self.text.insert("end", "\n")

        if in_code and code_lines:
            self._insert_code_block(code_lines)
        self.text.configure(state="disabled")
        self.text.see("1.0")

    def _insert_code_block(self, lines: List[str]) -> None:
        for code_line in lines:
            self.text.insert("end", code_line + "\n", "md_code_block")
        self.text.insert("end", "\n")

    def _insert_inline(self, text: str, base_tag: Optional[str] = None) -> None:
        text = text or ""
        pos = 0
        for match in self.INLINE_RE.finditer(text):
            if match.start() > pos:
                self._insert_segment(text[pos : match.start()], base_tag)
            raw = match.group(0)
            if raw.startswith("**") and raw.endswith("**"):
                self._insert_segment(raw[2:-2], self._combine(base_tag, "md_bold"))
            elif raw.startswith("__") and raw.endswith("__"):
                self._insert_segment(raw[2:-2], self._combine(base_tag, "md_bold"))
            elif raw.startswith("`") and raw.endswith("`"):
                self._insert_segment(raw[1:-1], self._combine(base_tag, "md_code"))
            elif (raw.startswith("*") and raw.endswith("*")) or (raw.startswith("_") and raw.endswith("_")):
                self._insert_segment(raw[1:-1], self._combine(base_tag, "md_italic"))
            else:
                link = re.match(r"\[([^\]]+)\]\(([^)]+)\)", raw)
                if link:
                    self._link_index += 1
                    tag_name = f"md_link_{self._link_index}"
                    url = link.group(2).strip()
                    self._link_urls[tag_name] = url
                    self.text.tag_configure(tag_name, foreground="#2563eb", underline=True)
                    self.text.tag_bind(tag_name, "<Button-1>", lambda _e, u=url: webbrowser.open(u))
                    label = link.group(1)
                    tags = self._combine(base_tag, tag_name) or tag_name
                    self.text.insert("end", label, tags)  # type: ignore[arg-type]
                else:
                    self._insert_segment(raw, base_tag)
            pos = match.end()
        if pos < len(text):
            self._insert_segment(text[pos:], base_tag)

    @staticmethod
    def _combine(base_tag: Optional[str], extra: str):
        if base_tag and base_tag != extra:
            return (base_tag, extra)
        return extra

    def _insert_segment(self, segment: str, tags) -> None:
        if not segment:
            return
        if tags:
            self.text.insert("end", segment, tags)  # type: ignore[arg-type]
        else:
            self.text.insert("end", segment)

    def get_text(self) -> str:
        return self._raw

    def see_end(self) -> None:
        self.text.see("end")

