"""主窗口。

图形界面使用 Python 标准库 tkinter/ttk，不依赖 PyQt，降低安装门槛。
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Sequence

from .. import __author__, __version__
from ..analyzer import local_analysis
from ..auto_reply import AutoReplyEvent, AutoReplyService
from ..config import AppConfig, config_path
from ..deepseek import DeepSeekClient, DeepSeekError, UsageInfo
from ..importers import ChatImportError, import_file
from ..media_ai import enrich_media_messages
from ..models import ChatSession, Message, clean_name
from ..sample_data import write_sample_chat
from ..storage import Database
from ..wechat import WeChatError, create_backend, wxauto_diagnostics, wxauto_status
from .dialogs import ImportDialog, TextDialog
from .widgets import ChatTranscript, CheckMarkButton, MarkdownText, ScrollableFrame


APP_TITLE = f"Crush Chat Analyzer · 聊天分析助手 v{__version__} · 制作者：{__author__}"

# 轻量“现代感”配色
BG = "#f3f4f6"
CARD = "#ffffff"
PRIMARY = "#4f46e5"
PRIMARY_DARK = "#4338ca"
TEXT = "#111827"
MUTED = "#6b7280"
BORDER = "#e5e7eb"


class MainWindow(tk.Tk):
    def __init__(self, app_config: Optional[AppConfig] = None, db: Optional[Database] = None):
        super().__init__()
        self.app_config = app_config or AppConfig.load()
        self.db = db or Database()
        self.current_session: Optional[ChatSession] = None
        self.backend = create_backend()
        self.auto_service = AutoReplyService(
            self.app_config,
            db=self.db,
            backend=self.backend,
            callback=self._on_auto_event,
        )

        self._events: "queue.Queue[tuple]" = queue.Queue()
        self._busy_count = 0
        self._closed = False
        self._last_wechat_chat = ""

        self.title(APP_TITLE)
        self.geometry("1100x720")
        self.minsize(900, 620)
        self._maximize_window()
        self._set_window_icon()
        self._build_styles()
        self._build_header()
        self._build_body()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)
        self._refresh_sessions()
        self._load_settings_into_ui()
        self._update_wechat_status()
        self._set_status("就绪。建议先导入一份聊天记录，再到设置中填写 DeepSeek API Key。")
        self.after(700, self._maybe_show_welcome)

    # ==================================================================
    # 样式与布局
    # ==================================================================
    def _build_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        family = self.app_config.font_family or "Microsoft YaHei UI"
        base_font = (family, 10)
        title_font = (family, 17, "bold")
        section_font = (family, 11, "bold")

        self.option_add("*Font", base_font)
        style.configure(".", font=base_font, background=BG, foreground=TEXT)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD, relief="flat")
        style.configure("Header.TFrame", background=PRIMARY)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("HeaderTitle.TLabel", font=title_font, background=PRIMARY, foreground="#ffffff")
        style.configure("HeaderSub.TLabel", background=PRIMARY, foreground="#e0e7ff")
        style.configure("HeaderInfo.TLabel", background=PRIMARY, foreground="#c7d2fe", font=(family, 9))
        style.configure("Title.TLabel", font=title_font, background=BG, foreground=TEXT)
        style.configure("Section.TLabel", font=section_font, background=BG, foreground=TEXT)
        style.configure("CardSection.TLabel", font=section_font, background=CARD, foreground=TEXT)
        style.configure("Hint.TLabel", foreground=MUTED, background=BG)
        style.configure("CardHint.TLabel", foreground=MUTED, background=CARD)
        style.configure("Status.TLabel", foreground="#374151", background="#e5e7eb", padding=(10, 6))
        style.configure("TButton", padding=(10, 6), borderwidth=0)
        style.configure("Accent.TButton", foreground="#ffffff", background=PRIMARY, padding=(14, 7), borderwidth=0)
        style.map(
            "Accent.TButton",
            background=[("active", PRIMARY_DARK), ("disabled", "#a5b4fc")],
            foreground=[("disabled", "#ffffff")],
        )
        style.configure(
            "BigAccent.TButton",
            foreground="#ffffff",
            background=PRIMARY,
            padding=(22, 11),
            font=(family, 11, "bold"),
            borderwidth=0,
        )
        style.map(
            "BigAccent.TButton",
            background=[("active", PRIMARY_DARK), ("disabled", "#a5b4fc")],
            foreground=[("disabled", "#ffffff")],
        )
        style.configure("SaveBar.TFrame", background="#eef2ff")
        style.configure("SaveBar.TLabel", background="#eef2ff", foreground=TEXT)
        style.configure("Header.TButton", foreground=PRIMARY, background="#ffffff", padding=(12, 6), borderwidth=0)
        style.map("Header.TButton", background=[("active", "#eef2ff")])
        style.configure("Ghost.TButton", foreground=PRIMARY, background=BG, padding=(10, 6), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#e0e7ff")])
        style.configure("Danger.TButton", foreground="#b91c1c", padding=(10, 6))
        style.configure("Treeview", rowheight=30, font=base_font, background=CARD, fieldbackground=CARD, borderwidth=0)
        style.map("Treeview", background=[("selected", "#e0e7ff")], foreground=[("selected", PRIMARY_DARK)])
        style.configure("Treeview.Heading", font=(family, 10, "bold"), background="#eef2ff", foreground="#3730a3")
        style.configure("TLabelframe", background=BG, borderwidth=1, relief="solid", padding=4)
        style.configure("TLabelframe.Label", background=BG, font=section_font, foreground=TEXT)
        style.configure("Card.TLabelframe", background=CARD, borderwidth=1, relief="solid", padding=4)
        style.configure("Card.TLabelframe.Label", background=CARD, font=section_font, foreground=TEXT)
        style.configure("TCheckbutton", background=BG)
        style.configure("TRadiobutton", background=BG)
        style.configure("TEntry", padding=(8, 6), fieldbackground="#ffffff")
        style.configure("TSpinbox", padding=(6, 5))
        style.configure("TCombobox", padding=(5, 4))
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 6, 0, 0))
        style.configure(
            "TNotebook.Tab",
            padding=(20, 11),
            background="#e5e7eb",
            foreground="#374151",
            font=(family, 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", CARD), ("active", "#eef2ff")],
            foreground=[("selected", PRIMARY), ("active", PRIMARY_DARK)],
        )

    def _maximize_window(self) -> None:
        """默认最大化窗口，Windows 优先使用 zoomed 状态。"""
        try:
            self.state("zoomed")
            return
        except tk.TclError:
            pass
        try:
            self.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass
        # 其他平台兜底：铺满屏幕
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")

    def _resource_path(self, relative: str) -> Path:
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base) / relative
        return Path(__file__).resolve().parents[2] / relative

    def _set_window_icon(self) -> None:
        icon_ico = self._resource_path("assets/icon.ico")
        try:
            if icon_ico.exists():
                self.iconbitmap(default=str(icon_ico))
                return
        except Exception:
            pass
        icon_png = self._resource_path("assets/icon.png")
        try:
            if icon_png.exists():
                self._icon_photo = tk.PhotoImage(file=str(icon_png))
                self.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    def _build_header(self) -> None:
        family = self.app_config.font_family or "Microsoft YaHei UI"
        header = tk.Frame(self, bg=PRIMARY)
        header.pack(side="top", fill="x")

        inner = tk.Frame(header, bg=PRIMARY)
        inner.pack(fill="x", padx=18, pady=(14, 8))
        left = tk.Frame(inner, bg=PRIMARY)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(
            left,
            text="Crush Chat Analyzer · 聊天分析助手",
            bg=PRIMARY,
            fg="#ffffff",
            font=(family, 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left,
            text="分析聊天情绪与表达，辅助 AI 回复和自动回复",
            bg=PRIMARY,
            fg="#e0e7ff",
            font=(family, 9),
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            left,
            text=f"v{__version__} · 制作者：{__author__}",
            bg=PRIMARY,
            fg="#c7d2fe",
            font=(family, 8),
        ).pack(anchor="w")

        right = tk.Frame(inner, bg=PRIMARY)
        right.pack(side="right")
        for text, command, primary in (
            ("导入聊天记录", self._import_chat, True),
            ("连接微信", self._connect_wechat, False),
            ("使用说明", self._show_help, False),
            ("关于", self._show_about, False),
        ):
            bg = "#ffffff" if primary else "#6366f1"
            fg = PRIMARY if primary else "#ffffff"
            active_bg = "#eef2ff" if primary else "#4f46e5"
            tk.Button(
                right,
                text=text,
                command=command,
                bg=bg,
                fg=fg,
                activebackground=active_bg,
                activeforeground=fg,
                relief="flat",
                bd=0,
                padx=13,
                pady=7,
                cursor="hand2",
                font=(family, 9),
            ).pack(side="left", padx=4)

        info = tk.Frame(header, bg=PRIMARY)
        info.pack(fill="x", padx=18, pady=(0, 10))
        self.api_status_var = tk.StringVar(value="")
        self.usage_last_var = tk.StringVar(value="本次：暂无调用")
        self.usage_total_var = tk.StringVar(value="累计：0 次 · 0 tokens · ¥0.0000")
        tk.Label(info, textvariable=self.api_status_var, bg=PRIMARY, fg="#e0e7ff", font=(family, 9)).pack(side="left")
        tk.Label(info, text="  |  ", bg=PRIMARY, fg="#818cf8", font=(family, 9)).pack(side="left")
        tk.Label(info, textvariable=self.usage_last_var, bg=PRIMARY, fg="#e0e7ff", font=(family, 9)).pack(side="left")
        tk.Label(info, text="  |  ", bg=PRIMARY, fg="#818cf8", font=(family, 9)).pack(side="left")
        tk.Label(info, textvariable=self.usage_total_var, bg=PRIMARY, fg="#e0e7ff", font=(family, 9)).pack(side="left")

    def _build_body(self) -> None:
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(side="top", fill="both", expand=True, padx=14, pady=(12, 8))
        self.sidebar = self._build_sidebar(body)
        self.notebook = ttk.Notebook(body)
        body.add(self.sidebar, weight=1)
        body.add(self.notebook, weight=4)
        self._build_chat_tab()
        self._build_analysis_tab()
        self._build_reply_tab()
        self._build_wechat_tab()
        self._build_settings_tab()

    def _build_sidebar(self, master: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(master, padding=12, style="Card.TFrame")
        ttk.Label(frame, text="会话列表", style="CardSection.TLabel").pack(anchor="w", pady=(0, 8))
        search_row = ttk.Frame(frame, style="Card.TFrame")
        search_row.pack(fill="x", pady=(0, 8))
        self.session_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.session_search_var)
        search_entry.pack(fill="x")
        self.session_search_var.trace_add("write", lambda *_a: self._refresh_sessions())
        search_entry.insert(0, "")
        ttk.Label(search_row, text="搜索会话 / 联系人", style="CardHint.TLabel").pack(anchor="w", pady=(3, 0))

        columns = ("name", "count", "updated")
        self.session_tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        self.session_tree.heading("name", text="会话")
        self.session_tree.heading("count", text="消息")
        self.session_tree.heading("updated", text="更新时间")
        self.session_tree.column("name", width=170, anchor="w")
        self.session_tree.column("count", width=54, anchor="center", stretch=False)
        self.session_tree.column("updated", width=110, anchor="center", stretch=False)
        self.session_tree.pack(fill="both", expand=True)
        self.session_tree.bind("<<TreeviewSelect>>", self._on_session_select)

        btns = ttk.Frame(frame, style="Card.TFrame")
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="导入", style="Accent.TButton", command=self._import_chat).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="删除", style="Danger.TButton", command=self._delete_selected_session).pack(side="left", padx=4)
        ttk.Button(btns, text="刷新", style="Ghost.TButton", command=self._refresh_sessions).pack(side="left", padx=4)
        return frame

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel", anchor="w").pack(fill="x")

    # ==================================================================
    # 标签页
    # ==================================================================
    def _build_chat_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="聊天记录")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        self.chat_title_var = tk.StringVar(value="未选择会话")
        ttk.Label(toolbar, textvariable=self.chat_title_var, style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(toolbar, text="导出聊天记录", style="Ghost.TButton", command=self._export_chat).grid(
            row=0, column=1, sticky="e"
        )

        role_frame = ttk.Frame(toolbar)
        role_frame.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(role_frame, text="我是：").pack(side="left")
        self.role_var = tk.StringVar()
        self.role_combo = ttk.Combobox(role_frame, textvariable=self.role_var, width=16, state="readonly")
        self.role_combo.pack(side="left", padx=(2, 8))
        self.role_combo.bind("<<ComboboxSelected>>", self._on_role_changed)

        search_frame = ttk.Frame(toolbar)
        search_frame.grid(row=1, column=1, sticky="e", pady=(6, 0))
        ttk.Label(search_frame, text="搜索：").pack(side="left")
        self.chat_search_var = tk.StringVar()
        self.chat_search_var.trace_add("write", lambda *_a: self._on_chat_search_changed())
        ttk.Entry(search_frame, textvariable=self.chat_search_var, width=14).pack(side="left")
        ttk.Button(search_frame, text="上一个", command=self._chat_search_prev).pack(side="left", padx=(4, 0))
        ttk.Button(search_frame, text="下一个", command=self._chat_search_next).pack(side="left", padx=(2, 0))
        ttk.Button(search_frame, text="清除", command=lambda: self.chat_search_var.set("")).pack(side="left", padx=(2, 0))

        stats_bar = ttk.Frame(tab, style="Card.TFrame")
        stats_bar.pack(fill="x", pady=(0, 8))
        self.chat_stats_var = tk.StringVar(value="消息总览：请选择会话")
        ttk.Label(stats_bar, textvariable=self.chat_stats_var, style="CardSection.TLabel").pack(
            anchor="w", padx=12, pady=8
        )

        self.chat_transcript = ChatTranscript(tab)
        self.chat_transcript.pack(fill="both", expand=True)

    def _build_analysis_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="AI 分析")

        identity_row = ttk.Frame(tab)
        identity_row.pack(fill="x", pady=(0, 6))
        ttk.Label(identity_row, text="分析前请确认：我是").pack(side="left")
        self.analysis_role_var = tk.StringVar()
        self.analysis_role_combo = ttk.Combobox(
            identity_row, textvariable=self.analysis_role_var, state="readonly", width=20
        )
        self.analysis_role_combo.pack(side="left", padx=(4, 8))
        self.analysis_role_combo.bind("<<ComboboxSelected>>", self._on_analysis_role_changed)
        ttk.Label(
            identity_row,
            text="默认优先选“我”；如果识别反了，手动切换即可。",
            style="Hint.TLabel",
        ).pack(side="left")

        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=(0, 8))
        controls.columnconfigure(3, weight=1)
        ttk.Label(controls, text="分析重点：").grid(row=0, column=0, sticky="w")
        self.focus_var = tk.StringVar(value=self.app_config.analysis_focus or "综合解读")
        ttk.Combobox(
            controls,
            textvariable=self.focus_var,
            values=["综合解读", "对方情绪", "对方态度", "我的表达", "下一步行动"],
            width=12,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(controls, text="补充说明：").grid(row=0, column=2, sticky="w")
        self.extra_instruction_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.extra_instruction_var).grid(row=0, column=3, sticky="ew", padx=(4, 0))
        btns = ttk.Frame(controls)
        btns.grid(row=1, column=0, columnspan=4, sticky="e", pady=(6, 0))
        ttk.Button(btns, text="本地速览", command=self._show_local_analysis).pack(side="left", padx=4)
        ttk.Button(btns, text="DeepSeek 分析", style="Accent.TButton", command=self._analyze).pack(side="left", padx=4)
        ttk.Button(btns, text="导出报告", command=self._export_analysis).pack(side="left", padx=4)
        ttk.Button(btns, text="复制", command=self._copy_analysis).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text=(
                "提示：AI 分析只读取最近“AI 上下文消息数”条消息。\n"
                "修改位置：设置 → 分析上下文；条数越多，token 消耗越高。\n"
                "图片/语音识别：设置 → 图片 / 语音内容识别。"
            ),
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        card = ttk.Frame(tab, style="Card.TFrame")
        card.pack(fill="both", expand=True)
        self.analysis_text = MarkdownText(card)
        self.analysis_text.pack(fill="both", expand=True)
        self._set_analysis_text("尚未分析。点击“本地速览”或“DeepSeek 分析”开始。")

    def _build_reply_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="智能回复")

        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 8))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="想要的效果：").grid(row=0, column=0, sticky="w")
        self.reply_instruction_var = tk.StringVar(value="自然接住对方的话，让聊天舒服地继续")
        ttk.Entry(top, textvariable=self.reply_instruction_var).grid(row=0, column=1, sticky="ew", padx=(4, 10))
        ttk.Label(top, text="条数：").grid(row=0, column=2, sticky="w")
        self.reply_count_var = tk.IntVar(value=3)
        ttk.Spinbox(top, from_=1, to=5, textvariable=self.reply_count_var, width=4).grid(
            row=0, column=3, sticky="w", padx=(2, 10)
        )
        ttk.Button(top, text="生成回复建议", style="Accent.TButton", command=self._generate_replies).grid(
            row=1, column=0, columnspan=4, sticky="e", pady=(6, 0)
        )

        context_frame = ttk.Labelframe(tab, text="最近聊天上下文", padding=6)
        context_frame.pack(fill="x", pady=(0, 8))
        self.reply_context_text = tk.Text(context_frame, height=8, wrap="word", relief="flat", font=("Microsoft YaHei UI", 9))
        context_scroll = ttk.Scrollbar(context_frame, orient="vertical", command=self.reply_context_text.yview)
        self.reply_context_text.configure(yscrollcommand=context_scroll.set, state="disabled")
        self.reply_context_text.pack(side="left", fill="both", expand=True)
        context_scroll.pack(side="right", fill="y")

        self.reply_room_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.reply_room_var, style="Hint.TLabel").pack(anchor="w", pady=(0, 4))

        target_row = ttk.Frame(tab)
        target_row.pack(fill="x", pady=(0, 6))
        ttk.Label(target_row, text="搜索联系人：").pack(side="left")
        self.reply_target_search_var = tk.StringVar()
        ttk.Entry(target_row, textvariable=self.reply_target_search_var, width=16).pack(side="left", padx=(4, 10))
        self.reply_target_search_var.trace_add("write", lambda *_a: self._refresh_reply_targets())
        ttk.Label(target_row, text="发送到微信：").pack(side="left")
        self.reply_target_var = tk.StringVar()
        self.reply_target_combo = ttk.Combobox(
            target_row, textvariable=self.reply_target_var, state="readonly", width=22
        )
        self.reply_target_combo.pack(side="left", padx=(4, 6))
        ttk.Button(target_row, text="刷新目标", command=self._refresh_reply_targets).pack(side="left")

        knowledge_row = ttk.Frame(tab)
        knowledge_row.pack(fill="x", pady=(0, 6))
        ttk.Label(
            knowledge_row,
            text="提示：AI 不知道的梗、游戏、网络用语，可在“设置 → 梗/游戏知识库”补充，生成回复时会参考。",
            style="Hint.TLabel",
        ).pack(side="left")
        ttk.Button(
            knowledge_row,
            text="去设置知识库",
            style="Ghost.TButton",
            command=self._open_knowledge_settings,
        ).pack(side="right")

        self.reply_scroll = ScrollableFrame(tab)
        self.reply_scroll.pack(fill="both", expand=True)
        self.reply_suggestions_frame = self.reply_scroll.inner

    def _build_wechat_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="微信接入 / 自动回复")

        # 共享变量
        self.var_wechat_self_name = tk.StringVar(value=self.app_config.wechat_self_name)
        self.var_auto_dry_run = tk.BooleanVar(value=bool(self.app_config.auto_reply_dry_run))
        self.var_auto_poll = tk.StringVar(value=str(self.app_config.auto_reply_poll_interval))
        self.var_auto_quiet = tk.StringVar(value=str(self.app_config.auto_reply_quiet_seconds))
        self.var_auto_max_per_min = tk.StringVar(value=str(self.app_config.auto_reply_max_per_minute))
        self.var_auto_skip = tk.StringVar(value=self.app_config.auto_reply_skip_keywords)
        self.var_auto_style = tk.StringVar(value=self.app_config.auto_reply_style or "自然、简短、像本人")
        self.wechat_search_var = tk.StringVar()
        self.wechat_chat_all: List[str] = []

        top = ttk.Labelframe(tab, text="微信连接", padding=8)
        top.pack(fill="x", pady=(0, 8))
        self.wechat_status_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.wechat_status_var, wraplength=760, justify="left").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(6, 0))
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="我的微信昵称：").grid(row=0, column=0, sticky="w")
        ttk.Entry(row, textvariable=self.var_wechat_self_name).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        btns = ttk.Frame(top)
        btns.pack(fill="x", pady=(6, 0))
        self.wechat_install_btn = ttk.Button(btns, text="一键安装后端", style="Accent.TButton", command=self._install_wxauto)
        self.wechat_install_btn.pack(side="left", padx=(0, 4))
        self.wechat_connect_btn = ttk.Button(btns, text="连接微信", command=self._connect_wechat)
        self.wechat_connect_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="刷新微信会话", command=self._refresh_wechat_sessions).pack(side="left", padx=4)
        ttk.Button(btns, text="诊断后端", command=self._diagnose_wxauto).pack(side="left", padx=4)
        ttk.Button(btns, text="断开微信连接", style="Ghost.TButton", command=self._disconnect_wechat).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text=(
                "提示：AI 上下文条数和图片/语音识别都在“设置”页配置。\n"
                "断开微信连接会同时停止自动回复，但不会删除聊天记录。\n"
                "自动回复建议先保持演练模式，确认效果后再真实发送。"
            ),
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        middle = ttk.Frame(tab)
        middle.pack(fill="both", expand=True)
        left = ttk.Labelframe(middle, text="微信会话列表", padding=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        wx_search_row = ttk.Frame(left)
        wx_search_row.pack(fill="x", pady=(0, 4))
        ttk.Label(wx_search_row, text="搜索会话：").pack(side="left")
        wx_search_var_entry = ttk.Entry(wx_search_row, textvariable=self.wechat_search_var)
        wx_search_var_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.wechat_search_var.trace_add("write", lambda *_a: self._refresh_wechat_chat_list_view())
        self.wechat_chat_list = tk.Listbox(left, height=9, activestyle="none", font=("Microsoft YaHei UI", 10))
        wx_scroll = ttk.Scrollbar(left, orient="vertical", command=self.wechat_chat_list.yview)
        self.wechat_chat_list.configure(yscrollcommand=wx_scroll.set)
        self.wechat_chat_list.pack(side="left", fill="both", expand=True)
        self.wechat_chat_list.bind("<<ListboxSelect>>", self._on_wechat_chat_select)
        wx_scroll.pack(side="right", fill="y")
        wx_btns = ttk.Labelframe(left, text="会话操作", padding=4)
        wx_btns.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(wx_btns, text="读取并导入到左侧", command=self._import_selected_wechat_chat).pack(side="left", padx=(0, 4))
        ttk.Button(wx_btns, text="设为自动回复对象", command=self._set_auto_reply_contact).pack(side="left", padx=4)

        right = ttk.Labelframe(middle, text="自动回复控制台", padding=6)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        auto_row = ttk.Frame(right)
        auto_row.pack(fill="x", pady=(0, 6))
        CheckMarkButton(auto_row, text="演练模式（只生成不发送）", variable=self.var_auto_dry_run).pack(side="left")
        ttk.Label(auto_row, text="  轮询秒数：").pack(side="left")
        ttk.Spinbox(auto_row, from_=2, to=60, textvariable=self.var_auto_poll, width=4).pack(side="left")
        ttk.Label(auto_row, text="  风格：").pack(side="left")
        ttk.Combobox(
            auto_row,
            textvariable=self.var_auto_style,
            values=(
                "自然、简短、像本人",
                "温柔体贴",
                "轻松幽默",
                "高冷简洁",
                "热情主动",
                "正式礼貌",
                "俏皮可爱",
            ),
            width=12,
            state="readonly",
        ).pack(side="left")
        auto_btns = ttk.Frame(right)
        auto_btns.pack(fill="x", pady=(0, 6))
        self.auto_start_btn = ttk.Button(auto_btns, text="开始自动回复", style="Accent.TButton", command=self._start_auto_reply)
        self.auto_start_btn.pack(side="left", padx=(0, 4))
        self.auto_stop_btn = ttk.Button(auto_btns, text="停止", command=self._stop_auto_reply, state="disabled")
        self.auto_stop_btn.pack(side="left", padx=4)
        self.auto_contact_var = tk.StringVar(value="未选择")
        ttk.Label(auto_btns, textvariable=self.auto_contact_var, style="Hint.TLabel").pack(side="left", padx=(12, 0))
        self.auto_status_var = tk.StringVar(value="未运行")
        ttk.Label(auto_btns, textvariable=self.auto_status_var, style="Hint.TLabel").pack(side="right")

        knowledge_row = ttk.Frame(right)
        knowledge_row.pack(fill="x", pady=(0, 4))
        ttk.Label(
            knowledge_row,
            text="自动回复会参考“设置 → 梗/游戏知识库”。",
            style="Hint.TLabel",
        ).pack(side="left")
        ttk.Button(
            knowledge_row,
            text="去设置知识库",
            style="Ghost.TButton",
            command=self._open_knowledge_settings,
        ).pack(side="right")

        self.auto_log = tk.Text(right, height=10, wrap="word", relief="flat", font=("Microsoft YaHei UI", 9), state="disabled")
        log_scroll = ttk.Scrollbar(right, orient="vertical", command=self.auto_log.yview)
        self.auto_log.configure(yscrollcommand=log_scroll.set)
        self.auto_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="设置")
        scroll = ScrollableFrame(tab)
        self.settings_scroll = scroll
        scroll.pack(fill="both", expand=True)
        frame = scroll.inner
        ttk.Label(
            frame,
            text=(
                "这里是全部设置项，按顺序配置即可：\n"
                "接口 → 费用 → 图片/语音识别 → 分析上下文 → 自动回复。\n"
                "修改后点击“保存设置”。"
            ),
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(4, 6))

        save_bar = ttk.Frame(frame, style="SaveBar.TFrame", padding=10)
        save_bar.pack(fill="x", padx=4, pady=(2, 8))
        ttk.Label(
            save_bar,
            text="修改设置后必须点击右侧按钮保存，否则不会生效。",
            style="SaveBar.TLabel",
        ).pack(side="left")
        ttk.Button(save_bar, text="保存设置", style="BigAccent.TButton", command=self._save_settings).pack(side="right")

        self.var_api_key = tk.StringVar()
        self.var_base_url = tk.StringVar()
        self.var_model = tk.StringVar()
        self.var_temperature = tk.StringVar()
        self.var_max_tokens = tk.StringVar()
        self.var_timeout = tk.StringVar()
        self.var_max_context_messages = tk.StringVar()
        self.var_max_context_chars = tk.StringVar()
        self.var_max_import_messages = tk.StringVar()
        self.var_auto_reply_greeting = tk.StringVar()
        self.var_auto_allow_emoji = tk.BooleanVar()
        self.var_price_hit = tk.StringVar()
        self.var_price_miss = tk.StringVar()
        self.var_price_output = tk.StringVar()
        self.var_price_currency = tk.StringVar()
        self.var_media_enabled = tk.BooleanVar()
        self.var_media_base_url = tk.StringVar()
        self.var_media_api_key = tk.StringVar()
        self.var_media_vision_model = tk.StringVar()
        self.var_media_asr_model = tk.StringVar()
        self.var_media_max_items = tk.StringVar()
        self.usage_settings_var = tk.StringVar(value="累计：0 次 · 0 tokens · ¥0.0000")

        ttk.Label(
            frame,
            text="1. 接口配置：填写 DeepSeek 或其他 OpenAI 兼容接口的 Key、地址和模型名。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(6, 0))
        api_frame = ttk.Labelframe(frame, text="DeepSeek / OpenAI 兼容接口", padding=10)
        api_frame.pack(fill="x", pady=(0, 10), padx=4)
        self._settings_entry(api_frame, "API Key", self.var_api_key, width=60, show="*", row=0)
        self._settings_entry(api_frame, "Base URL", self.var_base_url, width=45, row=1)
        self._settings_entry(api_frame, "模型", self.var_model, width=30, row=2)
        self._settings_entry(api_frame, "Temperature", self.var_temperature, width=12, row=3)
        self._settings_entry(api_frame, "Max tokens", self.var_max_tokens, width=12, row=4)
        self._settings_entry(api_frame, "超时（秒）", self.var_timeout, width=12, row=5)
        ttk.Label(
            api_frame,
            text="默认是 DeepSeek：https://api.deepseek.com + deepseek-chat。\n其他 OpenAI 兼容服务填写以 /v1 结尾的地址即可。",
            style="Hint.TLabel",
            justify="left",
        ).grid(row=6, column=1, sticky="w", pady=(4, 0))

        ttk.Label(
            frame,
            text="2. 费用估算：填写模型单价，用于估算本次和累计 token 费用。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(6, 0))
        pricing_frame = ttk.Labelframe(frame, text="Token 用量与费用估算", padding=10)
        pricing_frame.pack(fill="x", pady=(0, 10), padx=4)
        self._settings_entry(pricing_frame, "缓存命中输入 / 1M", self.var_price_hit, width=14, row=0)
        self._settings_entry(pricing_frame, "缓存未命中输入 / 1M", self.var_price_miss, width=14, row=1)
        self._settings_entry(pricing_frame, "输出 / 1M", self.var_price_output, width=14, row=2)
        self._settings_entry(pricing_frame, "货币", self.var_price_currency, width=10, row=3)
        ttk.Label(
            pricing_frame,
            text=(
                "默认按 deepseek-chat 常见价格预填：0.5 / 2 / 8。\n"
                "模型价格会调整，请以官网账单为准；这里只做估算，不作为扣费依据。"
            ),
            style="Hint.TLabel",
            justify="left",
        ).grid(row=4, column=1, sticky="w", pady=(4, 0))
        ttk.Label(pricing_frame, textvariable=self.usage_settings_var, style="Hint.TLabel").grid(
            row=5, column=1, sticky="w", pady=(8, 0)
        )
        ttk.Button(pricing_frame, text="累计用量清零", style="Danger.TButton", command=self._reset_usage).grid(
            row=5, column=0, sticky="e", padx=(0, 8), pady=(8, 0)
        )

        ttk.Label(
            frame,
            text="3. 图片 / 语音识别：可选；需要支持视觉和语音转文字的接口。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(6, 0))
        media_frame = ttk.Labelframe(frame, text="图片 / 语音内容识别（可选）", padding=10)
        media_frame.pack(fill="x", pady=(0, 10), padx=4)
        CheckMarkButton(
            media_frame,
            text="启用图片 OCR / 语音转文字（需要支持视觉和 ASR 的 OpenAI 兼容接口）",
            variable=self.var_media_enabled,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self._settings_entry(media_frame, "媒体 Base URL", self.var_media_base_url, width=45, row=1)
        self._settings_entry(media_frame, "媒体 API Key", self.var_media_api_key, width=45, show="*", row=2)
        self._settings_entry(media_frame, "视觉模型", self.var_media_vision_model, width=24, row=3)
        self._settings_entry(media_frame, "语音转文字模型", self.var_media_asr_model, width=24, row=4)
        self._settings_entry(media_frame, "每次最多识别条数", self.var_media_max_items, width=10, row=5)
        ttk.Label(
            media_frame,
            text=(
                "不配置时只显示 [图片] / [语音] 标签。\n"
                "视觉模型走 /chat/completions，语音走 /audio/transcriptions。\n"
                "表情包默认识别为 [动画表情]，不做内容描述。"
            ),
            style="Hint.TLabel",
            justify="left",
        ).grid(row=6, column=1, sticky="w", pady=(6, 0))

        ttk.Label(
            frame,
            text="4. 分析上下文：控制 AI 读取多少消息、多少字符，以及微信导入上限。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(6, 0))
        context_frame = ttk.Labelframe(frame, text="分析上下文", padding=10)
        context_frame.pack(fill="x", pady=(0, 10), padx=4)
        self._settings_entry(context_frame, "AI 上下文消息数", self.var_max_context_messages, width=12, row=0)
        self._settings_entry(context_frame, "AI 上下文字符数", self.var_max_context_chars, width=12, row=1)
        self._settings_entry(context_frame, "微信导入最多消息数", self.var_max_import_messages, width=12, row=2)
        ttk.Label(context_frame, text="System persona（可选）").grid(row=3, column=0, sticky="ne", padx=(0, 8), pady=6)
        self.persona_text = tk.Text(context_frame, height=4, width=60, wrap="word", font=("Microsoft YaHei UI", 9))
        self.persona_text.grid(row=3, column=1, sticky="we", pady=6)
        ttk.Label(context_frame, text="可以让回复更像你，例如“话不多、偶尔冷幽默”。", style="Hint.TLabel").grid(
            row=4, column=1, sticky="w"
        )
        ttk.Label(context_frame, text="梗/游戏知识库（可选）").grid(row=5, column=0, sticky="ne", padx=(0, 8), pady=6)
        self.knowledge_text = tk.Text(context_frame, height=4, width=60, wrap="word", font=("Microsoft YaHei UI", 9))
        self.knowledge_text.grid(row=5, column=1, sticky="we", pady=6)
        ttk.Label(
            context_frame,
            text="把对方常提到的梗、游戏、网络用语解释写在这里，AI 分析和自动回复会参考。",
            style="Hint.TLabel",
            justify="left",
        ).grid(row=6, column=1, sticky="w")
        ttk.Label(
            context_frame,
            text=(
                "取值范围：\n"
                "AI 上下文消息数：10 ~ 5000，默认 120\n"
                "AI 上下文字符数：1000 ~ 500000，默认 18000\n"
                "微信导入最多消息数：10 ~ 200000，默认 5000\n"
                "条数越多，分析越全面，token 消耗越高。"
            ),
            style="Hint.TLabel",
            justify="left",
        ).grid(row=7, column=1, sticky="w", pady=(4, 0))

        ttk.Label(
            frame,
            text="5. 自动回复：控制轮询间隔、发送限速、跳过关键词和默认风格。",
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(6, 0))
        auto_frame = ttk.Labelframe(frame, text="自动回复默认值", padding=10)
        auto_frame.pack(fill="x", pady=(0, 10), padx=4)
        self._settings_entry(auto_frame, "等待对方说完（秒）", self.var_auto_quiet, width=12, row=0)
        self._settings_entry(auto_frame, "轮询秒数", self.var_auto_poll, width=12, row=1)
        self._settings_entry(auto_frame, "每分钟上限", self.var_auto_max_per_min, width=12, row=2)
        self._settings_entry(auto_frame, "跳过关键词", self.var_auto_skip, width=48, row=3)
        ttk.Label(auto_frame, text="自动回复风格").grid(row=4, column=0, sticky="e", padx=(0, 8), pady=6)
        ttk.Combobox(
            auto_frame,
            textvariable=self.var_auto_style,
            values=(
                "自然、简短、像本人",
                "温柔体贴",
                "轻松幽默",
                "高冷简洁",
                "热情主动",
                "正式礼貌",
                "俏皮可爱",
            ),
            width=24,
        ).grid(row=4, column=1, sticky="w", pady=6)
        CheckMarkButton(
            auto_frame,
            text="允许使用微信表情代码：[旺柴][呲牙][OK][合十][尴尬]",
            variable=self.var_auto_allow_emoji,
        ).grid(row=5, column=1, sticky="w", pady=6)
        CheckMarkButton(auto_frame, text="默认进入演练模式（只生成不发送）", variable=self.var_auto_dry_run).grid(
            row=6, column=1, sticky="w", pady=6
        )
        ttk.Label(auto_frame, text="跳过关键词用英文/中文逗号分隔。", style="Hint.TLabel").grid(row=7, column=1, sticky="w")

        action = ttk.Frame(frame)
        action.pack(fill="x", pady=(4, 20), padx=4)
        ttk.Button(action, text="保存设置", style="BigAccent.TButton", command=self._save_settings).pack(side="left", padx=(0, 8))
        ttk.Button(action, text="测试 API 连接", command=self._test_api).pack(side="left", padx=4)
        ttk.Button(action, text="清除 API Key", style="Danger.TButton", command=self._clear_api_key).pack(side="left", padx=4)
        ttk.Button(action, text="查看配置目录", command=self._open_config_dir).pack(side="left", padx=4)

        ttk.Label(
            frame,
            text=(
                "隐私提醒：API Key 保存在本机用户目录，不会上传到除模型服务商以外的位置。\n"
                "聊天记录保存在本地 SQLite 数据库中。请勿把导出的报告随意发给别人。\n"
                "AI 分析只是概率推测，不要用它替代真实沟通，也不要反复测试对方。"
            ),
            style="Hint.TLabel",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 20))

    def _settings_entry(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.Variable,
        width: int = 30,
        row: int = 0,
        show: str = "",
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=(0, 8), pady=6)
        entry = ttk.Entry(parent, textvariable=variable, width=width, show=show)
        entry.grid(row=row, column=1, sticky="w", pady=6)
        return entry
    # ==================================================================
    # 会话加载与聊天展示
    # ==================================================================
    def _refresh_sessions(self) -> None:
        try:
            sessions = self.db.list_sessions()
        except Exception as exc:  # noqa: BLE001
            self._show_error("读取会话失败", exc)
            return
        keyword = (self.session_search_var.get() if hasattr(self, "session_search_var") else "").strip().lower()
        selected = self.current_session.id if self.current_session else ""
        tree = self.session_tree
        tree.delete(*tree.get_children())
        shown = 0
        for session in sessions:
            name = session.name or "未命名会话"
            search_blob = f"{name} {session.other_sender} {session.source}".lower()
            if keyword and keyword not in search_blob:
                continue
            count = session.meta.get("message_count") or len(session.messages)
            updated = session.updated_at.strftime("%m-%d %H:%M") if session.updated_at else ""
            iid = session.id
            tree.insert("", "end", iid=iid, values=(name, count, updated))
            shown += 1
        if selected and tree.exists(selected):
            tree.selection_set(selected)
            tree.see(selected)
        self._update_api_status()

    def _on_session_select(self, _event=None) -> None:
        selection = self.session_tree.selection()
        if not selection:
            return
        self._load_session(selection[0])

    def _load_session(self, session_id: str) -> None:
        session = self.db.get_session(session_id)
        if session is None:
            return
        self.current_session = session
        # 先根据“我是”标记消息角色，再刷新统计和聊天记录。
        self._update_role_combo(session)
        title = f"{session.name}"
        if session.other_sender:
            title += f" · 对方：{session.other_sender}"
        title += f" · {len(session.messages)} 条消息"
        self.chat_title_var.set(title)
        self_count = sum(1 for m in session.messages if m.is_self)
        other_count = len(session.messages) - self_count
        timestamps = [m.timestamp for m in session.messages if m.timestamp]
        if timestamps:
            span = f"{min(timestamps):%Y-%m-%d} ~ {max(timestamps):%Y-%m-%d}"
        else:
            span = "时间未知"
        self.chat_stats_var.set(
            f"共 {len(session.messages)} 条消息　·　我 {self_count} 条　·　对方 {other_count} 条　·　{span}"
        )
        self.chat_transcript.set_session(session)
        self._refresh_reply_context()
        self._set_status(f"已加载会话：{session.name}（{len(session.messages)} 条消息）。")
        # 自动回填最近一次 AI 分析
        record = self.db.get_latest_analysis(session.id, "deepseek") or self.db.get_latest_analysis(session.id, "local")
        if record:
            self._set_analysis_text(record.content)
        else:
            self._set_analysis_text("尚未分析。点击“本地速览”或“DeepSeek 分析”开始。")

    def _update_role_combo(self, session: ChatSession) -> None:
        senders = [s for s in session.senders if s]
        values = list(senders)
        if not values:
            values = ["我", "对方"]
        if session.self_sender and session.self_sender not in values:
            values.insert(0, session.self_sender)
        # 默认优先把“我”当作自己；如果识别反了，用户可手动切换。
        if not session.self_sender and "我" in values:
            session.self_sender = "我"
            session.normalize_roles("我")
            try:
                self.db.save_session(session)
            except Exception:
                pass
        self.role_combo.configure(values=values)
        if hasattr(self, "analysis_role_combo"):
            self.analysis_role_combo.configure(values=values)
        if session.self_sender:
            self.role_var.set(session.self_sender)
            if hasattr(self, "analysis_role_var"):
                self.analysis_role_var.set(session.self_sender)
        elif len(values) == 1:
            self.role_var.set(values[0])
            if hasattr(self, "analysis_role_var"):
                self.analysis_role_var.set(values[0])
        else:
            self.role_var.set("")
            if hasattr(self, "analysis_role_var"):
                self.analysis_role_var.set("")

    def _on_role_changed(self, _event=None) -> None:
        self._apply_self_name(self.role_var.get())

    def _on_analysis_role_changed(self, _event=None) -> None:
        self._apply_self_name(self.analysis_role_var.get())

    def _apply_self_name(self, self_name: str) -> None:
        if not self.current_session:
            return
        self_name = clean_name(self_name)
        self.current_session.normalize_roles(self_name)
        self.db.save_session(self.current_session)
        self.chat_transcript.set_session(self.current_session)
        self._refresh_reply_context()
        self.role_var.set(self_name)
        if hasattr(self, "analysis_role_var"):
            self.analysis_role_var.set(self_name)
        self.chat_title_var.set(
            f"{self.current_session.name} · 我：{self.current_session.self_sender or '未指定'} · "
            f"{len(self.current_session.messages)} 条消息"
        )
        self._set_status(f"已把“{self_name or '未指定'}”标记为我。")

    def _on_chat_search_changed(self) -> None:
        if not hasattr(self, "chat_transcript"):
            return
        count = self.chat_transcript.highlight(self.chat_search_var.get())
        if self.chat_search_var.get().strip():
            if count:
                self._set_status(f"找到 {count} 处匹配，当前 1/{count}。")
            else:
                self._set_status("没有找到匹配。")

    def _chat_search_prev(self) -> None:
        self._goto_chat_match(-1)

    def _chat_search_next(self) -> None:
        self._goto_chat_match(1)

    def _goto_chat_match(self, delta: int) -> None:
        if not hasattr(self, "chat_transcript") or not self.chat_search_var.get().strip():
            return
        index, total = self.chat_transcript.goto_match(delta)
        if total:
            self._set_status(f"匹配第 {index}/{total} 处。")
        else:
            self._set_status("没有找到匹配。")

    def _refresh_reply_context(self) -> None:
        if not hasattr(self, "reply_context_text"):
            return
        session = self.current_session
        self.reply_context_text.configure(state="normal")
        self.reply_context_text.delete("1.0", "end")
        if session is None:
            self.reply_context_text.insert("1.0", "请先选择会话。")
            self.reply_room_var.set("")
        else:
            messages = session.messages[-12:]
            lines: List[str] = []
            for msg in messages:
                role = "我" if msg.is_self else (session.other_sender or msg.sender or "对方")
                time_part = f"[{msg.timestamp:%m-%d %H:%M}] " if msg.timestamp else ""
                lines.append(f"{time_part}{role}: {msg.content}")
            self.reply_context_text.insert("1.0", "\n".join(lines) or "当前会话没有消息。")
            self.reply_room_var.set(f"当前会话：{session.name}")
        self.reply_context_text.configure(state="disabled")
        self._clear_reply_suggestions()
        self._refresh_reply_targets()

    def _wechat_chat_names(self) -> List[str]:
        raw = list(self.wechat_chat_all) if hasattr(self, "wechat_chat_all") and self.wechat_chat_all else []
        if not raw and hasattr(self, "wechat_chat_list"):
            raw = [str(self.wechat_chat_list.get(i)) for i in range(self.wechat_chat_list.size())]
        names: List[str] = []
        for name in raw:
            cleaned = clean_name(name)
            if cleaned and cleaned not in names:
                names.append(cleaned)
        return names

    def _refresh_reply_targets(self) -> None:
        if not hasattr(self, "reply_target_combo"):
            return
        keyword = (
            self.reply_target_search_var.get().strip().lower()
            if hasattr(self, "reply_target_search_var")
            else ""
        )
        all_names = self._wechat_chat_names()
        values: List[str] = []
        for name in all_names:
            if name and name not in values and (not keyword or keyword in name.lower()):
                values.append(name)
        current = clean_name(self.reply_target_var.get())
        if current and current in all_names and current not in values:
            values.insert(0, current)
        self.reply_target_combo.configure(values=values)
        if current in values:
            return
        session = self.current_session
        for candidate in (
            self._last_wechat_chat,
            self._selected_wechat_chat() if hasattr(self, "wechat_chat_list") else "",
            session.other_sender if session else "",
            session.name if session else "",
        ):
            if candidate and candidate in values:
                self.reply_target_var.set(candidate)
                return
        self.reply_target_var.set(values[0] if values else "")

    def _on_wechat_chat_select(self, _event=None) -> None:
        chat = self._selected_wechat_chat()
        if not chat:
            return
        self._last_wechat_chat = chat
        if hasattr(self, "reply_target_var"):
            self.reply_target_var.set(chat)

    # ==================================================================
    # AI 分析
    # ==================================================================
    def _show_local_analysis(self) -> None:
        session = self.current_session
        if session is None:
            messagebox.showinfo("还没有会话", "请先导入或选择一个聊天会话。", parent=self)
            return
        if not (session.self_sender or "").strip():
            messagebox.showinfo(
                "请先确认“我是”",
                "分析前请先在 AI 分析页顶部的“我是”下拉框选择你自己的昵称，\n"
                "否则软件无法正确区分你和对方。",
                parent=self,
            )
            return
        text = local_analysis(session)
        self._set_analysis_text(text)
        if session.id:
            self.db.add_analysis(session.id, "local", text, model="local")
        self._set_status("已生成本地速览。")

    def _analyze(self) -> None:
        session = self.current_session
        if session is None:
            messagebox.showinfo("还没有会话", "请先导入或选择一个聊天会话。", parent=self)
            return
        if not (session.self_sender or "").strip():
            messagebox.showinfo(
                "请先确认“我是”",
                "分析前请先在 AI 分析页顶部的“我是”下拉框选择你自己的昵称，\n"
                "否则 AI 可能把两个人的身份分析反。",
                parent=self,
            )
            return
        if not (self.app_config.api_key or "").strip():
            if messagebox.askyesno(
                "未配置 API Key",
                "还没有填写 DeepSeek API Key。\n是否先查看不需要联网的本地速览？",
                parent=self,
            ):
                self._show_local_analysis()
            else:
                self.notebook.select(4)
                messagebox.showinfo("配置 API Key", "请到“设置”页填写 API Key 后再进行分析。", parent=self)
            return

        focus = self.focus_var.get()
        extra = self.extra_instruction_var.get().strip()
        self._set_analysis_text("DeepSeek 正在阅读你们的聊天记录，请稍候…")
        self._set_status("正在请求 DeepSeek 分析…")

        def work():
            client = DeepSeekClient(self.app_config)
            text = client.analyze(session, focus=focus, extra_instruction=extra)
            return text, client.last_model or client.config.model, client.last_usage_info

        def done(result):
            text, model, usage = result
            self._set_analysis_text(text)
            if self.current_session and self.current_session.id == session.id:
                self.db.add_analysis(session.id, "deepseek", text, model=model)
            self._record_usage(usage, source="AI 分析")
            self._set_status("AI 分析完成。")

        self._run_async(work, done, lambda exc: self._analysis_error(exc, session))

    def _analysis_error(self, exc: Exception, session: ChatSession) -> None:
        if isinstance(exc, DeepSeekError):
            message = exc.user_message
        else:
            message = str(exc)
        self._set_analysis_text(f"分析失败：{message}\n\n你可以先点击“本地速览”查看不依赖大模型的统计信息。")
        self._set_status("AI 分析失败。")
        messagebox.showerror("分析失败", message, parent=self)

    def _set_analysis_text(self, text: str) -> None:
        self.analysis_text.render(text or "")

    def _copy_analysis(self) -> None:
        text = self.analysis_text.get_text().strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("分析报告已复制到剪贴板。")

    def _export_analysis(self) -> None:
        text = self.analysis_text.get_text().strip()
        if not text:
            messagebox.showinfo("没有内容", "还没有可导出的分析报告。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出分析报告",
            defaultextension=".md",
            initialfile="聊天分析报告.md",
            filetypes=[("Markdown", "*.md"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(text, encoding="utf-8")
        self._set_status(f"报告已导出：{path}")

    def _export_chat(self) -> None:
        session = self.current_session
        if session is None or not session.messages:
            messagebox.showinfo("没有聊天记录", "请先选择或导入一个会话。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出聊天记录",
            defaultextension=".txt",
            initialfile=f"{session.name}_聊天记录.txt",
            filetypes=[("文本文件", "*.txt"), ("CSV 文件", "*.csv"), ("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".csv":
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["时间", "发送人", "是否我", "内容"])
                    for msg in session.messages:
                        writer.writerow([
                            msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if msg.timestamp else "",
                            msg.sender or ("我" if msg.is_self else "对方"),
                            "是" if msg.is_self else "否",
                            msg.content,
                        ])
            elif suffix == ".json":
                payload = {
                    "name": session.name,
                    "self_sender": session.self_sender,
                    "other_sender": session.other_sender,
                    "messages": [
                        {
                            "time": msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if msg.timestamp else "",
                            "sender": msg.sender,
                            "is_self": msg.is_self,
                            "content": msg.content,
                        }
                        for msg in session.messages
                    ],
                }
                Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                lines = []
                for msg in session.messages:
                    time_part = f"[{msg.timestamp:%Y-%m-%d %H:%M:%S}] " if msg.timestamp else ""
                    role = "我" if msg.is_self else (session.other_sender or msg.sender or "对方")
                    lines.append(f"{time_part}{role}: {msg.content}")
                Path(path).write_text("\n".join(lines), encoding="utf-8")
            self._set_status(f"聊天记录已导出（双方共 {len(session.messages)} 条）：{path}")
            messagebox.showinfo("导出成功", f"已导出双方共 {len(session.messages)} 条消息。\n\n{path}", parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc), parent=self)

    # ==================================================================
    # 导入与删除
    # ==================================================================
    def _import_chat(self) -> None:
        dialog = ImportDialog(self)
        self.wait_window(dialog)
        if not dialog.result:
            return
        result = dialog.result
        self._set_status("正在导入聊天记录…")

        def work():
            return import_file(
                result["path"],
                self_name=result.get("self_name", ""),
                session_name=result.get("session_name", ""),
            )

        def done(import_result):
            session = import_result.session
            self.db.save_session(session)
            self._refresh_sessions()
            self.session_tree.selection_set(session.id)
            self.session_tree.see(session.id)
            self._load_session(session.id)
            warning = "\n".join(import_result.warnings)
            if warning:
                messagebox.showwarning("导入完成，但有提示", warning, parent=self)
            self._set_status(
                f"已导入 {len(session.messages)} 条消息，格式：{import_result.detected_format}。"
                "如需区分“我/对方”，请在聊天记录页选择“我是”。"
            )

        self._run_async(work, done, lambda exc: self._import_error(exc))

    def _import_error(self, exc: Exception) -> None:
        if isinstance(exc, ChatImportError):
            message = str(exc)
        else:
            message = f"导入失败：{exc}"
        messagebox.showerror("导入失败", message, parent=self)
        self._set_status("导入失败。")

    def _delete_selected_session(self) -> None:
        session = self.current_session
        if session is None:
            messagebox.showinfo("没有选中会话", "请先在左侧选择一个会话。", parent=self)
            return
        if not messagebox.askyesno("确认删除", f"删除会话“{session.name}”及其所有消息和分析记录？", parent=self):
            return
        self.db.delete_session(session.id)
        self.current_session = None
        self.chat_transcript.clear()
        self.chat_title_var.set("未选择会话")
        self._set_analysis_text("尚未分析。")
        self._refresh_sessions()
        self._refresh_reply_context()
        self._set_status("会话已删除。")

    def _maybe_show_welcome(self) -> None:
        if self._closed:
            return
        if self.db.get_setting("welcome.shown", False):
            return
        self.db.set_setting("welcome.shown", True)
        sample: Optional[Path] = Path(__file__).resolve().parents[2] / "examples" / "sample_chat.txt"
        # 单文件 exe 运行时不一定有 examples 目录，此时使用内置示例。
        if not sample.exists():
            try:
                sample = write_sample_chat()
            except Exception:
                sample = None
        message = (
            f"欢迎使用 Crush Chat Analyzer v{__version__}！\n\n"
            "0 基础使用顺序：\n"
            "1. 导入聊天记录（可以先导入示例）\n"
            "2. 在“聊天记录”页选择“我是：”\n"
            "3. 到“设置”填写 DeepSeek API Key\n"
            "4. 回到“AI 分析”开始分析\n\n"
            "核心程序不需要安装第三方依赖；\n"
            "单文件 exe 已内置示例数据和说明。\n"
            "只有微信接入需要可选的 wxauto。\n\n"
            "是否现在导入示例聊天记录？"
        )
        if sample is not None and sample.exists() and messagebox.askyesno("欢迎使用", message, parent=self):
            self._import_sample_chat(sample)
        else:
            messagebox.showinfo(
                "接下来怎么做",
                "你可以点击右上角“导入聊天记录”开始，\n"
                "也可以点击“使用说明”查看完整步骤。",
                parent=self,
            )

    def _import_sample_chat(self, sample: Path) -> None:
        self._set_status("正在导入示例聊天记录…")

        def work():
            return import_file(sample, self_name="我", session_name="示例聊天")

        def done(import_result):
            session = import_result.session
            self.db.save_session(session)
            self._refresh_sessions()
            self.session_tree.selection_set(session.id)
            self.session_tree.see(session.id)
            self._load_session(session.id)
            self._set_status("示例聊天已导入。可以点击“本地速览”或配置 API 后点击“DeepSeek 分析”。")
            messagebox.showinfo(
                "示例已导入",
                "示例聊天已导入左侧会话列表。\n\n"
                "接下来：\n"
                "1. 点击“本地速览”看统计\n"
                "2. 到“设置”填写 DeepSeek API Key\n"
                "3. 点击“DeepSeek 分析”",
                parent=self,
            )

        self._run_async(work, done, lambda exc: messagebox.showerror("导入示例失败", str(exc), parent=self))

    def _show_help(self) -> None:
        content = (
            f"Crush Chat Analyzer v{__version__} 使用说明\n"
            f"制作者：{__author__}\n"
            "========================================\n\n"
            "一、第一次使用\n"
            "1. 双击项目根目录“启动.bat”即可，核心程序不需要 pip 安装依赖。\n"
            "2. 也可以命令行启动：python main.py 或 python -m crush_analyzer。\n"
            "3. 进入“设置”填写 DeepSeek API Key，点击“测试 API 连接”。\n"
            "4. 第一次打开会提供内置示例数据，可以直接导入试跑。\n"
            "5. 在“聊天记录”页右上角选择“我是：”，让软件知道哪边是你。\n\n"
            "二、导入聊天记录\n"
            "- 文件支持：.txt / .csv / .tsv / .json / .jsonl。\n"
            "- 微信 PC 复制文本、WeChatMsg/PyWxDump 导出的 CSV/JSON 都能导入。\n"
            "- 常见列名会自动适配：StrTime、NickName、StrContent、IsSender、CreateTime 等。\n"
            "- 如果身份识别错误，切换到正确的“我是：”即可重新标记。\n\n"
            "三、AI 分析页\n"
            "- 本地速览：不需要 API Key，展示消息量、主动性、回复间隔、情绪词等统计。\n"
            "- DeepSeek 分析：生成情绪、兴趣信号、表达复盘、话术建议和下一步建议。\n"
            "- 分析结果支持 Markdown 展示：标题、列表、粗体、代码块、链接等。\n"
            "- 每次调用后的 token 和估算费用会显示在顶部信息栏。\n\n"
            "四、智能回复页\n"
            "- 输入你想要的效果，例如“自然接话”“低压力邀约”“先结束话题”。\n"
            "- 生成 1~5 条建议，每条都带风格、理由和风险等级。\n"
            "- 可以复制，也可以在已连接微信后直接发送。\n\n"
            "五、微信接入与自动回复\n"
            "- 需要 Windows + 微信 PC 版；exe 已内置 wechatauto 1.2.3 后端。\n"
            "- 不需要安装 Python 3.11，也不需要手动安装 wxauto。\n"
            "- 连接后刷新微信会话，选中联系人，可读取聊天或设为自动回复对象。\n"
            "- 自动回复默认是“演练模式”：只生成不发送。\n"
            "- 请务必先填写“我的微信昵称”，否则可能无法区分自己发的消息。\n"
            "- 对方明确拒绝、冷淡，或涉及转账/验证码/链接时，不建议自动回复。\n\n"
            "六、Token 与费用显示\n"
            "- 顶部信息栏显示：本次 token/费用、累计 token/费用。\n"
            "- 费用在“设置 → Token 用量与费用估算”中按 1M tokens 单价计算。\n"
            "- 默认预填 deepseek-chat 常见价格：缓存命中 0.5、未命中 2、输出 8。\n"
            "- 模型价格可能调整，实际扣费请以 DeepSeek 官方账单为准。\n"
            "- 可点击“累计用量清零”重新统计。\n\n"
            "七、隐私与边界\n"
            "- 聊天记录和 API Key 都只保存在本机用户目录。\n"
            "- 调用 API 时，选中的聊天上下文会发送给模型服务商。\n"
            "- AI 分析只是概率推测，不要当作读心术或诊断工具。\n"
            "- 不鼓励查岗、跟踪、操控、PUA、骚扰或未经同意的自动化回复。"
        )
        TextDialog(self, "使用说明", content, width=860, height=720)

    def _show_about(self) -> None:
        totals = self._usage_totals()
        message = (
            f"Crush Chat Analyzer\n"
            f"版本：v{__version__}\n"
            f"制作者：{__author__}\n\n"
            "默认模型：DeepSeek deepseek-chat\n"
            "界面：Python tkinter/ttk\n"
            "存储：本地 SQLite\n\n"
            f"累计调用：{totals['calls']} 次\n"
            f"累计 tokens：{totals['total_tokens']:,}\n"
            f"累计估算费用：{totals['cost']:.4f} {totals['currency']}\n\n"
            "AI 分析仅供沟通复盘参考，请尊重对方边界和隐私。"
        )
        messagebox.showinfo("关于 Crush Chat Analyzer", message, parent=self)

    def _open_knowledge_settings(self) -> None:
        self.notebook.select(4)
        try:
            self.update_idletasks()
            total_height = max(1, self.settings_scroll.inner.winfo_height())
            y = max(0, self.knowledge_text.winfo_y() - 40)
            self.settings_scroll.canvas.yview_moveto(min(1.0, y / total_height))
            self.knowledge_text.focus_set()
        except Exception:
            pass
        self._set_status("请在“设置 → 梗/游戏知识库”里填写内容，保存后 AI 分析和自动回复都会参考。")

    # ==================================================================
    # 智能回复
    # ==================================================================
    def _generate_replies(self) -> None:
        session = self.current_session
        if session is None:
            messagebox.showinfo("还没有会话", "请先导入或选择一个聊天会话。", parent=self)
            return
        if not (self.app_config.api_key or "").strip():
            if messagebox.askyesno(
                "未配置 API Key",
                "生成回复建议需要调用 DeepSeek。\n是否先查看本地速览？",
                parent=self,
            ):
                self._show_local_analysis()
            else:
                self.notebook.select(4)
            return

        instruction = self.reply_instruction_var.get().strip()
        count = int(self.reply_count_var.get() or 3)
        self._clear_reply_suggestions()
        label = ttk.Label(self.reply_suggestions_frame, text="正在生成回复建议…", style="Hint.TLabel")
        label.pack(anchor="w", padx=6, pady=6)
        self._set_status("正在生成回复建议…")

        def work():
            client = DeepSeekClient(self.app_config)
            read_room, replies = client.suggest_replies(session, instruction=instruction, count=count)
            return read_room, replies, client.last_usage_info

        def done(result):
            read_room, replies, usage = result
            self._render_reply_suggestions(read_room, replies)
            self._record_usage(usage, source="智能回复")
            self._set_status(f"已生成 {len(replies)} 条回复建议。")

        self._run_async(work, done, lambda exc: self._reply_error(exc))

    def _reply_error(self, exc: Exception) -> None:
        self._clear_reply_suggestions()
        message = exc.user_message if isinstance(exc, DeepSeekError) else str(exc)
        ttk.Label(
            self.reply_suggestions_frame,
            text=f"生成失败：{message}",
            style="Hint.TLabel",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=6, pady=6)
        self._set_status("回复建议生成失败。")
        messagebox.showerror("生成失败", message, parent=self)

    def _clear_reply_suggestions(self) -> None:
        for child in list(self.reply_suggestions_frame.winfo_children()):
            child.destroy()
        self.reply_room_var.set(f"当前会话：{self.current_session.name}" if self.current_session else "")

    def _render_reply_suggestions(self, read_room: str, replies: List[Dict[str, str]]) -> None:
        self._clear_reply_suggestions()
        if read_room:
            ttk.Label(
                self.reply_suggestions_frame,
                text=f"读空气：{read_room}",
                style="Hint.TLabel",
                wraplength=760,
                justify="left",
            ).pack(anchor="w", padx=6, pady=(4, 8))
        if not replies:
            ttk.Label(self.reply_suggestions_frame, text="没有生成可用的建议，换一种说法再试。", style="Hint.TLabel").pack(
                anchor="w", padx=6, pady=6
            )
            return
        for index, reply in enumerate(replies, start=1):
            card = ttk.Labelframe(
                self.reply_suggestions_frame,
                text=f"{index}. {reply.get('style') or '候选回复'}  ·  风险：{reply.get('risk') or '低'}",
                padding=8,
            )
            card.pack(fill="x", expand=True, padx=4, pady=5)
            text_widget = tk.Text(card, height=2, wrap="word", relief="flat", font=("Microsoft YaHei UI", 10))
            text_widget.insert("1.0", reply.get("text", ""))
            text_widget.configure(state="disabled")
            text_widget.pack(fill="x", anchor="w")
            reason = reply.get("reason") or ""
            if reason:
                ttk.Label(card, text=f"为什么：{reason}", style="Hint.TLabel", wraplength=740, justify="left").pack(
                    anchor="w", pady=(4, 2)
                )
            btns = ttk.Frame(card)
            btns.pack(fill="x", pady=(4, 0))
            ttk.Button(
                btns,
                text="复制",
                command=lambda t=reply.get("text", ""): self._copy_text(t),
            ).pack(side="left", padx=(0, 6))
            ttk.Button(
                btns,
                text="发送到微信",
                command=lambda t=reply.get("text", ""): self._send_reply_to_wechat(t),
            ).pack(side="left")

    def _copy_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("已复制到剪贴板。")

    def _send_reply_to_wechat(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if not self.backend.connected:
            if messagebox.askyesno("尚未连接微信", "还没有连接微信。是否现在去连接？", parent=self):
                self.notebook.select(3)
                self._connect_wechat()
            return
        valid_targets = self._wechat_chat_names()
        chat = self.reply_target_var.get().strip() if hasattr(self, "reply_target_var") else ""
        if not chat:
            chat = self._auto_reply_target()
        if not valid_targets:
            messagebox.showinfo(
                "请先刷新微信会话",
                "请先到“微信接入 / 自动回复”页点击“刷新微信会话”，再回来发送。",
                parent=self,
            )
            return
        if chat not in valid_targets:
            messagebox.showinfo(
                "请选择发送目标",
                "发送到微信前，请先在“发送到微信”下拉框选择一个有效联系人；\n"
                "如果列表是空的，请到“微信接入 / 自动回复”页刷新微信会话。",
                parent=self,
            )
            return
        if not messagebox.askyesno("确认发送", f"发送给“{chat}”：\n\n{text}", parent=self):
            return
        self._send_wechat_text(chat, text)

    def _send_wechat_text(self, chat: str, text: str) -> None:
        self._set_status(f"正在发送微信消息给 {chat}…")

        def work():
            self.backend.send_message(chat, text)
            return chat

        def done(sent_chat):
            sent_clean = clean_name(sent_chat)
            if self.current_session and (
                clean_name(self.current_session.source) == sent_clean
                or clean_name(self.current_session.other_sender) == sent_clean
                or clean_name(self.current_session.name) == sent_clean
            ):
                self.current_session.messages.append(
                    Message(sender=self.current_session.self_sender or "我", content=text, timestamp=None, is_self=True)
                )
                self.db.save_session(self.current_session)
                self.chat_transcript.set_session(self.current_session)
                self._refresh_reply_context()
            self._set_status(f"已发送给 {sent_chat}。")

        self._run_async(work, done, lambda exc: messagebox.showerror("发送失败", str(exc), parent=self))

    # ==================================================================
    # 微信接入
    # ==================================================================
    def _update_wechat_status(self) -> None:
        if not hasattr(self, "wechat_status_var"):
            return
        status = wxauto_status()
        if status["installed"]:
            backend_name = status.get("name") or "wxauto"
            self.wechat_status_var.set(
                f"微信自动化后端已就绪：{backend_name} {status['version'] or ''}。请确保 PC 微信已登录且窗口未最小化。"
            )
            self.wechat_connect_btn.configure(text="连接微信")
        else:
            error = (status.get("error") or "").strip()
            hint = "未检测到微信自动化后端。可以点击“一键安装 wxauto”，未安装时仍可导入 txt/csv/json 聊天记录。"
            if error and error != "未找到 wxauto":
                hint += f"\n导入错误：{error[:220]}"
            self.wechat_status_var.set(hint)
            self.wechat_connect_btn.configure(text="尝试连接")

    def _diagnose_wxauto(self) -> None:
        try:
            content = wxauto_diagnostics()
        except Exception as exc:  # noqa: BLE001
            content = f"诊断失败：{exc}"
        TextDialog(self, "wxauto 诊断信息", content, width=860, height=620)

    @staticmethod
    def _prefer_python_exe(exe: str) -> str:
        """如果拿到的是 pythonw.exe，优先换成同目录的 python.exe。"""
        if not exe:
            return exe
        path = Path(exe)
        if path.name.lower() == "pythonw.exe":
            python_exe = path.with_name("python.exe")
            if python_exe.exists():
                return str(python_exe)
        return exe

    @staticmethod
    def _py_launcher_pip_command(preferred_versions: Sequence[str] = ("-3.11", "-3.10")) -> Optional[List[str]]:
        """如果系统有 py launcher，优先找 3.11 / 3.10 来安装 wxauto。"""
        py = shutil.which("py")
        if not py:
            return None
        for version in preferred_versions:
            try:
                proc = subprocess.run(
                    [py, version, "-m", "pip", "--version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
            except Exception:  # noqa: BLE001
                continue
            if proc.returncode == 0:
                return [py, version, "-m", "pip"]
        return None

    def _pip_base_command(self) -> Optional[List[str]]:
        """返回可用于 pip 的系统 Python 命令。

        exe 打包版里 sys.executable 是 exe 本身，不能拿它执行 pip；
        因此需要寻找系统 Python / py launcher。
        wxauto 对 Python 3.13 兼容性可能不好，优先用 Python 3.11 / 3.10。
        """
        # 当前 Python 是 3.12+ 时，优先尝试 py -3.11 / py -3.10。
        if not getattr(sys, "frozen", False):
            if sys.version_info >= (3, 12):
                py_cmd = self._py_launcher_pip_command()
                if py_cmd:
                    return py_cmd
            return [self._prefer_python_exe(sys.executable), "-m", "pip"]

        py_cmd = self._py_launcher_pip_command()
        if py_cmd:
            return py_cmd
        for name in ("py", "python", "python3"):
            exe = shutil.which(name)
            if not exe:
                continue
            if name == "py":
                return [exe, "-3", "-m", "pip"]
            return [self._prefer_python_exe(exe), "-m", "pip"]
        return None

    def _install_wxauto(self) -> None:
        status = wxauto_status(force=True)
        if status["installed"]:
            messagebox.showinfo("已安装", f"wxauto 已经安装（版本 {status['version'] or '未知'}）。", parent=self)
            return
        base = self._pip_base_command()
        if base is None:
            messagebox.showerror(
                "找不到系统 Python",
                "当前是 exe 版本，并且没有在 PATH 中找到 python / py。\n\n"
                "请先安装 Python 3.10+，勾选 Add Python to PATH，\n"
                "然后重新打开软件再点“一键安装 wxauto”。\n"
                "也可以直接双击 启动.bat 使用源码版。",
                parent=self,
            )
            return
        pip_text = " ".join(base + ["install", "wxauto"])
        if not messagebox.askyesno(
            "安装 wxauto",
            f"将执行：\n{pip_text}\n\n"
            "需要联网。安装完成后会自动检测。\n是否继续？",
            parent=self,
        ):
            return
        self._set_status("正在安装 wxauto，请稍候…")
        self._append_auto_log(f"开始安装 wxauto：{pip_text}")

        def work():
            trusted = ["--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org"]
            attempts = [
                ("默认源", base + ["install", "wxauto"]),
                (
                    "PyPI 官方",
                    base + ["install", "wxauto", "-i", "https://pypi.org/simple"] + trusted,
                ),
                (
                    "清华镜像",
                    base
                    + ["install", "wxauto", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
                    + ["--trusted-host", "pypi.tuna.tsinghua.edu.cn"],
                ),
                (
                    "阿里云镜像",
                    base
                    + ["install", "wxauto", "-i", "https://mirrors.aliyun.com/pypi/simple/"]
                    + ["--trusted-host", "mirrors.aliyun.com"],
                ),
                (
                    "腾讯云镜像",
                    base
                    + ["install", "wxauto", "-i", "https://mirrors.cloud.tencent.com/pypi/simple"]
                    + ["--trusted-host", "mirrors.cloud.tencent.com"],
                ),
                (
                    "GitHub 主分支",
                    base + ["install", "https://github.com/cluic/wxauto/archive/refs/heads/main.zip"],
                ),
            ]
            outputs: List[str] = []
            code = 1
            for label, cmd in attempts:
                outputs.append(f"\n===== {label} =====\n$ {' '.join(cmd)}")
                try:
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=60,
                    )
                except subprocess.TimeoutExpired:
                    outputs.append("命令超时（60 秒）")
                    continue
                except Exception as exc:  # noqa: BLE001
                    outputs.append(str(exc))
                    continue
                code = int(proc.returncode)
                attempt_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
                outputs.append(attempt_output.strip() or "(无输出)")
                if code == 0:
                    break
            return code, "\n".join(outputs)

        def done(result):
            code, output = result
            lines = [line for line in (output or "").splitlines() if line.strip()]
            for line in lines[-30:]:
                self._append_auto_log(line[:240])
            if code == 0:
                wxauto_status(force=True)
                self._update_wechat_status()
                after = wxauto_status(force=True)
                if after.get("installed"):
                    self._set_status("wxauto 安装成功。")
                    messagebox.showinfo("安装成功", "wxauto 安装成功，请重新点击“连接微信”。", parent=self)
                else:
                    self._set_status("wxauto 已安装到系统 Python，但当前程序暂时无法导入。")
                    messagebox.showwarning(
                        "安装成功，但当前程序无法加载",
                        "wxauto 已经安装到系统 Python，但当前 exe 仍无法导入它。\n\n"
                        "建议：\n"
                        "1. 关闭本程序，重新执行 打包成exe.bat；\n"
                        "2. 或者直接用 启动.bat 以源码版运行。\n\n"
                        "可以点击“诊断 wxauto”查看搜索路径和导入错误。",
                        parent=self,
                    )
            else:
                self._set_status("wxauto 安装失败。")
                low = (output or "").lower()
                compatibility_hint = ""
                if "from versions: none" in low or "no matching distribution" in low:
                    compatibility_hint = (
                        "\n\n检测到“没有可用版本”，常见原因：\n"
                        "1. 当前 Python 版本过新，wxauto 可能还不支持 Python 3.13；\n"
                        "2. 当前镜像没有同步到 wxauto；\n"
                        "3. 网络被代理/防火墙拦截。\n\n"
                        "如果是 Python 3.13，建议安装 Python 3.11，然后执行：\n"
                        "py -3.11 -m pip install wxauto -i https://pypi.tuna.tsinghua.edu.cn/simple\n"
                        "py -3.11 main.py"
                    )
                messagebox.showerror(
                    "安装失败",
                    "wxauto 安装失败。\n\n"
                    f"Python 版本：{sys.version.split()[0]}\n"
                    f"可执行文件：{base[0]}\n"
                    f"{compatibility_hint}\n\n"
                    "完整错误输出已经写入日志区域，也可以点击“诊断 wxauto”。\n\n"
                    f"最后 1000 字输出：\n{(output or '')[-1000:]}",
                    parent=self,
                )

        self._run_async(work, done, lambda exc: messagebox.showerror("安装失败", str(exc), parent=self))

    def _connect_wechat(self) -> None:
        self._set_status("正在连接微信…")

        def work():
            if not self.backend.connected:
                # 用户可能在软件运行期间才安装 wxauto；这里重新检测并替换后端。
                status = wxauto_status(force=True)
                if status.get("installed"):
                    self.backend = create_backend()
                return self.backend.connect()
            return "微信已连接。"

        def done(message: str):
            self.auto_service.backend = self.backend
            self.wechat_connect_btn.configure(text="已连接")
            self.wechat_status_var.set(message)
            self._set_status(message)
            self._refresh_wechat_sessions()

        def error(exc: Exception):
            self.wechat_connect_btn.configure(text="连接微信")
            self.wechat_status_var.set(str(exc))
            self._set_status("微信连接失败。")
            messagebox.showerror("微信连接失败", str(exc), parent=self)

        self._run_async(work, done, error)

    def _disconnect_wechat(self) -> None:
        try:
            self.auto_service.stop()
            self.backend.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self.wechat_connect_btn.configure(text="连接微信")
        self._update_wechat_status()
        self._set_status("已断开微信连接（如果有）。")

    def _refresh_wechat_sessions(self) -> None:
        if not self.backend.connected:
            if not messagebox.askyesno("尚未连接微信", "还没有连接微信，是否现在连接？", parent=self):
                return
            self._connect_wechat()
            return
        self._set_status("正在读取微信会话列表…")

        def work():
            return self.backend.list_sessions()

        def done(names: List[str]):
            self.wechat_chat_all = list(names)
            self._refresh_wechat_chat_list_view()
            self._set_status(f"已读取 {len(names)} 个微信会话，可输入关键词搜索。")

        self._run_async(work, done, lambda exc: messagebox.showerror("读取失败", str(exc), parent=self))

    def _refresh_wechat_chat_list_view(self) -> None:
        if not hasattr(self, "wechat_chat_list"):
            return
        keyword = self.wechat_search_var.get().strip().lower() if hasattr(self, "wechat_search_var") else ""
        selected = self._selected_wechat_chat()
        names: List[str] = []
        for raw_name in getattr(self, "wechat_chat_all", []):
            name = clean_name(raw_name)
            if not name or name in names:
                continue
            if not keyword or keyword in name.lower():
                names.append(name)
        self.wechat_chat_list.delete(0, "end")
        selected_index = None
        for index, name in enumerate(names):
            self.wechat_chat_list.insert("end", name)
            if name == selected:
                selected_index = index
        if selected_index is not None:
            self.wechat_chat_list.selection_set(selected_index)
            self.wechat_chat_list.see(selected_index)
        self._refresh_reply_targets()

    def _selected_wechat_chat(self) -> str:
        selection = self.wechat_chat_list.curselection()
        if not selection:
            return ""
        return clean_name(self.wechat_chat_list.get(selection[0]))

    def _auto_reply_target(self) -> str:
        reply_target = clean_name(self.reply_target_var.get()) if hasattr(self, "reply_target_var") else ""
        chat = reply_target or clean_name(self._last_wechat_chat) or self._selected_wechat_chat()
        if chat:
            return chat
        if self.current_session:
            # 优先使用联系人昵称；source 只适合“从微信导入”的会话
            if self.current_session.platform == "wechat" and self.current_session.source and not Path(self.current_session.source).exists():
                return clean_name(self.current_session.source)
            return clean_name(self.current_session.other_sender or self.current_session.name)
        return ""

    def _set_auto_reply_contact(self) -> None:
        chat = self._selected_wechat_chat()
        if not chat:
            messagebox.showinfo("没有选中会话", "请先在微信会话列表中选择一个联系人。", parent=self)
            return
        self._last_wechat_chat = chat
        self.auto_contact_var.set(f"自动回复对象：{chat}")
        self._set_status(f"已选择自动回复对象：{chat}")

    def _import_selected_wechat_chat(self) -> None:
        chat = self._selected_wechat_chat()
        if not chat:
            messagebox.showinfo("没有选中会话", "请先在微信会话列表中选择一个联系人。", parent=self)
            return
        if not self.backend.connected:
            messagebox.showinfo("尚未连接微信", "请先连接微信。", parent=self)
            return
        self._set_status(f"正在读取“{chat}”的聊天记录…")

        def work():
            limit = max(1, int(self.app_config.max_import_messages or 5000))
            messages = self.backend.fetch_messages(chat, limit=limit)
            enrich_media_messages(messages, self.backend, self.app_config)
            return messages

        def done(messages: List[Message]):
            if not messages:
                messagebox.showinfo("没有消息", "没有读取到消息。请确认该会话已打开或 wxauto 版本兼容。", parent=self)
                return
            self_name = clean_name(self.app_config.wechat_self_name or self.var_wechat_self_name.get())
            if not self_name:
                for marker in ("我", "自己", "本人", "Self", "self", "me", "Me"):
                    if any(clean_name(m.sender) == marker for m in messages):
                        self_name = marker
                        break
            for msg in messages:
                if self_name:
                    msg.is_self = clean_name(msg.sender) == self_name
            other = next(
                (clean_name(m.sender) for m in messages if clean_name(m.sender) and clean_name(m.sender) != self_name),
                clean_name(chat),
            )
            session = ChatSession(
                name=clean_name(chat),
                platform="wechat",
                source=clean_name(chat),
                self_sender=self_name,
                other_sender=other,
                messages=messages,
            )
            self.db.save_session(session)
            self._refresh_sessions()
            self.session_tree.selection_set(session.id)
            self.session_tree.see(session.id)
            self._load_session(session.id)
            self._last_wechat_chat = chat
            self.auto_contact_var.set(f"自动回复对象：{chat}")
            self._set_status(f"已从微信导入“{chat}”的 {len(messages)} 条消息。")

        self._run_async(work, done, lambda exc: messagebox.showerror("读取失败", str(exc), parent=self))

    # ==================================================================
    # 自动回复
    # ==================================================================
    def _start_auto_reply(self) -> None:
        if self.auto_service.running:
            messagebox.showinfo("已在运行", "自动回复已经在运行。", parent=self)
            return
        if not self.backend.connected:
            if messagebox.askyesno("尚未连接微信", "自动回复需要先连接微信。是否现在连接？", parent=self):
                self._connect_wechat()
            return
        chat = self._auto_reply_target()
        if not chat:
            messagebox.showinfo("没有目标", "请先在微信会话列表选择联系人，或在左侧选择一个会话。", parent=self)
            return
        valid_targets = self._wechat_chat_names()
        if valid_targets and chat not in valid_targets:
            messagebox.showinfo(
                "目标无效",
                "当前目标不在微信会话列表中。\n请到“微信接入 / 自动回复”页刷新会话，并选择一个联系人。",
                parent=self,
            )
            return
        self_name = (self.var_wechat_self_name.get() or self.app_config.wechat_self_name or "").strip()
        if not self_name:
            if not messagebox.askyesno(
                "建议填写微信昵称",
                "还没有填写“我的微信昵称”，自动回复可能无法区分自己发的消息。\n是否仍然启动？",
                parent=self,
            ):
                return
        self.app_config.wechat_self_name = self_name
        self.app_config.auto_reply_contact = chat
        try:
            self.app_config.auto_reply_poll_interval = max(2, int(self.var_auto_poll.get()))
            self.app_config.auto_reply_max_per_minute = max(1, int(self.var_auto_max_per_min.get()))
        except ValueError:
            self.app_config.auto_reply_poll_interval = 5
            self.app_config.auto_reply_max_per_minute = 6
        self.app_config.auto_reply_dry_run = bool(self.var_auto_dry_run.get())
        self.app_config.auto_reply_skip_keywords = self.var_auto_skip.get().strip()
        self.auto_service.backend = self.backend
        self._last_wechat_chat = chat
        self.auto_contact_var.set(f"自动回复对象：{chat}")
        try:
            self.auto_service.start(chat, session_id=self.current_session.id if self.current_session else None)
        except ValueError as exc:
            messagebox.showerror("无法启动", str(exc), parent=self)
            return
        self.auto_start_btn.configure(state="disabled")
        self.auto_stop_btn.configure(state="normal")
        self.auto_status_var.set(f"运行中：{chat}")
        self._append_auto_log(f"启动自动回复：{chat}（演练模式：{self.app_config.auto_reply_dry_run}）")

    def _stop_auto_reply(self) -> None:
        self.auto_service.stop()
        self.auto_start_btn.configure(state="normal")
        self.auto_stop_btn.configure(state="disabled")
        self.auto_status_var.set("已停止")
        self._append_auto_log("已停止自动回复。")

    def _on_auto_event(self, event: AutoReplyEvent) -> None:
        # 这个回调可能来自后台线程，统一投递到 UI 队列
        self._events.put(("auto_event", event))

    def _handle_auto_event(self, event: AutoReplyEvent) -> None:
        self._append_auto_log(event.message)
        if event.kind == "usage":
            usage = event.data.get("usage_info")
            if isinstance(usage, UsageInfo):
                self._record_usage(usage, source="自动回复")
            self.auto_status_var.set("已记录用量")
        elif event.kind == "incoming":
            self.auto_status_var.set("收到新消息…")
        elif event.kind == "generated":
            self.auto_status_var.set("已生成回复")
        elif event.kind == "sent":
            self.auto_status_var.set("已发送回复")
        elif event.kind == "stopped":
            self.auto_status_var.set("已停止")
            self.auto_start_btn.configure(state="normal")
            self.auto_stop_btn.configure(state="disabled")
        elif event.kind == "error":
            self.auto_status_var.set("运行异常")
        elif event.kind == "status":
            self.auto_status_var.set(event.message[:40])

    def _append_auto_log(self, text: str) -> None:
        if not hasattr(self, "auto_log"):
            return
        import datetime

        self.auto_log.configure(state="normal")
        self.auto_log.insert("end", f"[{datetime.datetime.now():%H:%M:%S}] {text}\n")
        self.auto_log.configure(state="disabled")
        self.auto_log.see("end")

    # ==================================================================
    # 设置
    # ==================================================================
    def _load_settings_into_ui(self) -> None:
        cfg = self.app_config
        self.var_api_key.set(cfg.api_key or "")
        self.var_base_url.set(cfg.base_url or "https://api.deepseek.com")
        self.var_model.set(cfg.model or "deepseek-chat")
        self.var_temperature.set(str(cfg.temperature))
        self.var_max_tokens.set(str(cfg.max_tokens))
        self.var_timeout.set(str(cfg.timeout))
        self.var_max_context_messages.set(str(cfg.max_context_messages))
        self.var_max_context_chars.set(str(cfg.max_context_chars))
        self.var_max_import_messages.set(str(cfg.max_import_messages))
        self.var_wechat_self_name.set(cfg.wechat_self_name or "")
        self.var_auto_dry_run.set(bool(cfg.auto_reply_dry_run))
        self.var_auto_poll.set(str(cfg.auto_reply_poll_interval))
        self.var_auto_quiet.set(str(cfg.auto_reply_quiet_seconds))
        self.var_auto_max_per_min.set(str(cfg.auto_reply_max_per_minute))
        self.var_auto_skip.set(cfg.auto_reply_skip_keywords or "")
        self.var_auto_style.set(cfg.auto_reply_style or "自然、简短、像本人")
        self.var_auto_allow_emoji.set(bool(cfg.auto_reply_allow_emoji))
        self.var_price_hit.set(str(cfg.price_input_cache_hit))
        self.var_price_miss.set(str(cfg.price_input_cache_miss))
        self.var_price_output.set(str(cfg.price_output))
        self.var_price_currency.set(cfg.price_currency or "CNY")
        self.var_media_enabled.set(bool(cfg.media_ai_enabled))
        self.var_media_base_url.set(cfg.media_ai_base_url or "")
        self.var_media_api_key.set(cfg.media_ai_api_key or "")
        self.var_media_vision_model.set(cfg.media_vision_model or "")
        self.var_media_asr_model.set(cfg.media_asr_model or "whisper-1")
        self.var_media_max_items.set(str(cfg.media_max_items))
        self.persona_text.delete("1.0", "end")
        self.persona_text.insert("1.0", cfg.system_persona or "")
        self.knowledge_text.delete("1.0", "end")
        self.knowledge_text.insert("1.0", cfg.custom_knowledge or "")
        self._update_api_status()
        self._update_usage_display()

    def _collect_settings_from_ui(self) -> None:
        cfg = self.app_config
        cfg.api_key = self.var_api_key.get().strip()
        cfg.base_url = self.var_base_url.get().strip() or "https://api.deepseek.com"
        cfg.model = self.var_model.get().strip() or "deepseek-chat"
        cfg.temperature = self._safe_float(self.var_temperature.get(), 0.7, 0.0, 2.0)
        cfg.max_tokens = self._safe_int(self.var_max_tokens.get(), 1400, 64, 32000)
        cfg.timeout = self._safe_int(self.var_timeout.get(), 90, 10, 600)
        cfg.max_context_messages = self._safe_int(self.var_max_context_messages.get(), 120, 10, 5000)
        cfg.max_context_chars = self._safe_int(self.var_max_context_chars.get(), 18000, 1000, 500000)
        cfg.max_import_messages = self._safe_int(self.var_max_import_messages.get(), 5000, 10, 200000)
        cfg.wechat_self_name = self.var_wechat_self_name.get().strip()
        cfg.auto_reply_dry_run = bool(self.var_auto_dry_run.get())
        cfg.auto_reply_poll_interval = self._safe_int(self.var_auto_poll.get(), 5, 2, 300)
        cfg.auto_reply_quiet_seconds = self._safe_int(self.var_auto_quiet.get(), 6, 2, 60)
        cfg.auto_reply_max_per_minute = self._safe_int(self.var_auto_max_per_min.get(), 6, 1, 60)
        cfg.auto_reply_skip_keywords = self.var_auto_skip.get().strip()
        cfg.auto_reply_style = self.var_auto_style.get().strip() or "自然、简短、像本人"
        cfg.auto_reply_allow_emoji = bool(self.var_auto_allow_emoji.get())
        cfg.price_input_cache_hit = self._safe_float(self.var_price_hit.get(), 0.5, 0.0, 100000.0)
        cfg.price_input_cache_miss = self._safe_float(self.var_price_miss.get(), 2.0, 0.0, 100000.0)
        cfg.price_output = self._safe_float(self.var_price_output.get(), 8.0, 0.0, 100000.0)
        cfg.price_currency = (self.var_price_currency.get().strip() or "CNY").upper()
        cfg.media_ai_enabled = bool(self.var_media_enabled.get())
        cfg.media_ai_base_url = self.var_media_base_url.get().strip()
        cfg.media_ai_api_key = self.var_media_api_key.get().strip()
        cfg.media_vision_model = self.var_media_vision_model.get().strip()
        cfg.media_asr_model = self.var_media_asr_model.get().strip() or "whisper-1"
        cfg.media_max_items = self._safe_int(self.var_media_max_items.get(), 10, 0, 200)
        cfg.system_persona = self.persona_text.get("1.0", "end").strip()
        cfg.custom_knowledge = self.knowledge_text.get("1.0", "end").strip()
        cfg.analysis_focus = self.focus_var.get() if hasattr(self, "focus_var") else cfg.analysis_focus

    @staticmethod
    def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            result = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, result))

    @staticmethod
    def _safe_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            result = float(str(value).strip())
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, result))

    def _usage_totals(self) -> Dict[str, Any]:
        return {
            "calls": int(self.db.get_setting("usage.calls", 0) or 0),
            "prompt_tokens": int(self.db.get_setting("usage.prompt_tokens", 0) or 0),
            "completion_tokens": int(self.db.get_setting("usage.completion_tokens", 0) or 0),
            "total_tokens": int(self.db.get_setting("usage.total_tokens", 0) or 0),
            "cost": float(self.db.get_setting("usage.total_cost", 0.0) or 0.0),
            "currency": str(self.db.get_setting("usage.currency", self.app_config.price_currency or "CNY")),
        }

    def _record_usage(self, usage: UsageInfo, source: str = "") -> None:
        if not isinstance(usage, UsageInfo):
            return
        if usage.total_tokens <= 0 and usage.cost <= 0:
            return
        totals = self._usage_totals()
        totals["calls"] += 1
        totals["prompt_tokens"] += usage.input_tokens
        totals["completion_tokens"] += usage.completion_tokens
        totals["total_tokens"] += usage.total_tokens
        totals["cost"] += float(usage.cost)
        totals["currency"] = usage.currency or totals.get("currency") or "CNY"
        self.db.set_setting("usage.calls", totals["calls"])
        self.db.set_setting("usage.prompt_tokens", totals["prompt_tokens"])
        self.db.set_setting("usage.completion_tokens", totals["completion_tokens"])
        self.db.set_setting("usage.total_tokens", totals["total_tokens"])
        self.db.set_setting("usage.total_cost", round(totals["cost"], 6))
        self.db.set_setting("usage.currency", totals["currency"])
        label = f"[{source}] " if source else ""
        self.usage_last_var.set(f"本次 {label}{usage.format_short()}")
        self._update_usage_display()

    def _update_usage_display(self) -> None:
        if not hasattr(self, "usage_total_var"):
            return
        totals = self._usage_totals()
        symbol = {"CNY": "¥", "RMB": "¥", "USD": "$", "EUR": "€"}.get(
            str(totals["currency"]).upper(), str(totals["currency"])
        )
        text = f"累计：{totals['calls']} 次 · {totals['total_tokens']:,} tokens · {symbol}{totals['cost']:.4f}"
        self.usage_total_var.set(text)
        if hasattr(self, "usage_settings_var"):
            self.usage_settings_var.set(text)

    def _reset_usage(self) -> None:
        if not messagebox.askyesno("确认清零", "确定要把本机累计 token 和费用估算清零吗？", parent=self):
            return
        for key in (
            "usage.calls",
            "usage.prompt_tokens",
            "usage.completion_tokens",
            "usage.total_tokens",
            "usage.total_cost",
        ):
            self.db.set_setting(key, 0)
        self.db.set_setting("usage.currency", self.app_config.price_currency or "CNY")
        self.usage_last_var.set("本次：暂无调用")
        self._update_usage_display()
        self._set_status("累计用量已清零。")

    def _save_settings(self, silent: bool = False) -> None:
        self._collect_settings_from_ui()
        try:
            path = self.app_config.save()
        except OSError as exc:
            if not silent:
                messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self._update_api_status()
        self.auto_service.backend = self.backend
        if not silent:
            self._set_status(f"设置已保存到：{path}")
            messagebox.showinfo("保存成功", "设置已保存。", parent=self)

    def _test_api(self) -> None:
        self._save_settings(silent=True)
        if not (self.app_config.api_key or "").strip():
            messagebox.showwarning("缺少 API Key", "请先填写 DeepSeek API Key。", parent=self)
            return
        self._set_status("正在测试 API 连接…")

        def work():
            client = DeepSeekClient(self.app_config)
            reply = client.test_connection()
            return reply, client.last_usage_info

        def done(result):
            reply, usage = result
            self._record_usage(usage, source="连接测试")
            self._set_status("API 连接测试成功。")
            usage_text = f"\n\n本次用量：{usage.format_detail()}" if usage.total_tokens else ""
            messagebox.showinfo("连接成功", f"模型回复：{reply}{usage_text}", parent=self)

        def error(exc: Exception):
            message = exc.user_message if isinstance(exc, DeepSeekError) else str(exc)
            self._set_status("API 连接测试失败。")
            messagebox.showerror("连接失败", message, parent=self)

        self._run_async(work, done, error)

    def _clear_api_key(self) -> None:
        if not messagebox.askyesno("确认清除", "确定要清除本机保存的 API Key 吗？", parent=self):
            return
        self.var_api_key.set("")
        self.app_config.api_key = ""
        self._save_settings(silent=True)
        self._set_status("API Key 已清除。")

    def _update_api_status(self) -> None:
        if not hasattr(self, "api_status_var"):
            return
        if (self.app_config.api_key or "").strip():
            self.api_status_var.set(f"API：{self.app_config.model or 'deepseek-chat'} ✓")
        else:
            self.api_status_var.set("API：未配置（可先用本地速览）")

    def _open_config_dir(self) -> None:
        folder = config_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo("配置目录", f"配置目录：\n{folder}\n\n打开失败：{exc}", parent=self)

    # ==================================================================
    # 异步任务与状态
    # ==================================================================
    def _run_async(
        self,
        work: Callable[[], Any],
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        busy_text: str = "",
    ) -> None:
        self._busy_count += 1
        if busy_text:
            self._set_status(busy_text)

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._events.put(("error", on_error, exc))
            else:
                self._events.put(("success", on_success, result))

        threading.Thread(target=runner, name="crush-ui-task", daemon=True).start()

    def _poll_events(self) -> None:
        if self._closed:
            return
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]
                if kind == "success":
                    _, callback, result = event
                    self._busy_count = max(0, self._busy_count - 1)
                    if callable(callback):
                        callback(result)
                elif kind == "error":
                    _, callback, exc = event
                    self._busy_count = max(0, self._busy_count - 1)
                    if callable(callback):
                        callback(exc)
                    else:
                        self._show_error("操作失败", exc)
                elif kind == "auto_event":
                    _, auto_event = event
                    self._handle_auto_event(auto_event)
        except queue.Empty:
            pass
        finally:
            if not self._closed:
                self.after(120, self._poll_events)

    def _set_status(self, text: str) -> None:
        if hasattr(self, "status_var"):
            self.status_var.set(text)

    def _show_error(self, title: str, exc: Exception) -> None:
        message = exc.user_message if isinstance(exc, DeepSeekError) else str(exc)
        self._set_status(f"{title}：{message}")
        messagebox.showerror(title, message, parent=self)

    def _on_close(self) -> None:
        try:
            self.auto_service.stop(wait=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        self._closed = True
        self.destroy()


def run_app() -> None:
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    run_app()
