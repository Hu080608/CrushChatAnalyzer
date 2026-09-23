"""对话框。"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Dict, Optional


class ImportDialog(tk.Toplevel):
    """导入聊天记录对话框。

    使用自适应尺寸：小屏幕不会超出屏幕，大屏幕会更宽敞，
    且支持手动缩放，避免高 DPI 下控件被挤压。
    """

    def __init__(self, master: tk.Misc, initial_dir: str = ""):
        super().__init__(master)
        self.title("导入聊天记录")
        self.minsize(720, 430)
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()
        self.result: Optional[Dict[str, Any]] = None
        self._initial_dir = initial_dir

        outer = ttk.Frame(self, padding=22)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(outer, text="导入微信聊天记录", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="支持微信 PC 复制文本、WeChatMsg / PyWxDump 导出的 txt、csv、tsv、json、jsonl 文件。",
            style="Hint.TLabel",
            wraplength=680,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 14))

        form = ttk.Frame(outer, style="Card.TFrame", padding=16)
        form.grid(row=2, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="聊天文件 *", style="Card.TLabel").grid(
            row=0, column=0, sticky="e", padx=(0, 12), pady=9
        )
        self.path_var = tk.StringVar()
        self.path_entry = ttk.Entry(form, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=1, sticky="ew", pady=9)
        ttk.Button(form, text="浏览…", command=self._browse).grid(row=0, column=2, padx=(10, 0), pady=9)

        ttk.Label(form, text="我是谁（可选）", style="Card.TLabel").grid(
            row=1, column=0, sticky="e", padx=(0, 12), pady=9
        )
        self.self_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.self_var).grid(row=1, column=1, sticky="ew", pady=9)
        ttk.Label(
            form,
            text="填错也没关系，导入后可在“聊天记录”页右上角切换“我是：”。",
            style="CardHint.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=2, column=1, sticky="w", pady=(0, 8))

        ttk.Label(form, text="会话名称（可选）", style="Card.TLabel").grid(
            row=3, column=0, sticky="e", padx=(0, 12), pady=9
        )
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var).grid(row=3, column=1, sticky="ew", pady=9)

        ttk.Label(
            form,
            text="建议先导入项目里的示例数据试用；没有示例时软件会自动生成一份。",
            style="CardHint.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=4, column=1, sticky="w", pady=(4, 8))

        buttons = ttk.Frame(outer)
        buttons.grid(row=3, column=0, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="开始导入", style="Accent.TButton", command=self._ok).pack(side="right")

        self.update_idletasks()
        self.after(30, self._center_on_master)
        self.path_entry.focus_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _center_on_master(self) -> None:
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            width = min(max(self.winfo_reqwidth(), 720), max(560, screen_w - 80))
            height = min(max(self.winfo_reqheight(), 430), max(380, screen_h - 100))
            if self.master is not None:
                px = self.master.winfo_rootx()
                py = self.master.winfo_rooty()
                pw = self.master.winfo_width()
                ph = self.master.winfo_height()
            else:
                px = py = 0
                pw = screen_w
                ph = screen_h
            x = max(10, px + (pw - width) // 2)
            y = max(10, py + (ph - height) // 3)
            x = min(x, max(10, screen_w - width - 10))
            y = min(y, max(10, screen_h - height - 10))
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            self.geometry("760x460")

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择聊天记录文件",
            initialdir=self._initial_dir or None,
            filetypes=[
                ("聊天记录", "*.txt *.csv *.tsv *.json *.jsonl *.ndjson"),
                ("文本文件", "*.txt *.log"),
                ("CSV 文件", "*.csv *.tsv"),
                ("JSON 文件", "*.json *.jsonl *.ndjson"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.path_var.set(path)
            if not self.name_var.get().strip():
                import os

                self.name_var.set(os.path.splitext(os.path.basename(path))[0])

    def _ok(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            from tkinter import messagebox

            messagebox.showwarning("缺少文件", "请先选择聊天记录文件。", parent=self)
            return
        self.result = {
            "path": path,
            "self_name": self.self_var.get().strip(),
            "session_name": self.name_var.get().strip(),
        }
        self.destroy()


class TextDialog(tk.Toplevel):
    """只读文本查看窗口。"""

    def __init__(self, master: tk.Misc, title: str, content: str, width: int = 760, height: int = 560):
        super().__init__(master)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.transient(master)
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 10))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", content)
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Button(self, text="关闭", command=self.destroy).pack(pady=(0, 10))
