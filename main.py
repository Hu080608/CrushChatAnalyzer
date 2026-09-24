"""Crush Chat Analyzer 启动入口。

核心程序不依赖任何第三方 Python 包：
GUI = tkinter，数据库 = sqlite3，网络 = urllib/ssl。
双击“启动.bat”即可运行。
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


MIN_PYTHON = (3, 10)
try:
    from crush_analyzer import __version__ as APP_VERSION
except Exception:  # noqa: BLE001
    APP_VERSION = "dev"
APP_TITLE = f"Crush Chat Analyzer v{APP_VERSION}"


def _set_windows_dpi_awareness() -> None:
    """让 Windows 高分屏下界面不模糊。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
    except Exception:
        pass


def _fatal_message(title: str, text: str) -> None:
    """尽量用弹窗提示，失败则打印到控制台。"""
    print(f"[{title}] {text}")
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, text)
        root.destroy()
    except Exception:
        pass


def _write_crash_log(exc: BaseException) -> Path | None:
    try:
        log_dir = Path(__file__).resolve().parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "error.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        return log_path
    except Exception:
        return None


def _diagnose_wechat() -> int:
    """诊断微信自动化后端，并把结果写入 wx_diagnose.txt。"""
    lines: list[str] = []
    try:
        from crush_analyzer.wechat import WxautoBackend, wxauto_status

        status = wxauto_status(force=True)
        lines.append(f"installed: {status.get('installed')}")
        lines.append(f"name: {status.get('name')}")
        lines.append(f"version: {status.get('version')}")
        lines.append(f"error: {status.get('error')}")
        lines.append(f"frozen: {status.get('frozen')}")
        lines.append(f"python: {status.get('python')}")
        lines.append("search_paths:")
        lines.extend(f"  {p}" for p in (status.get("search_paths") or []))
        if status.get("installed"):
            backend = WxautoBackend()
            try:
                lines.append(f"connect: {backend.connect()}")
                sessions = backend.list_sessions()
                lines.append(f"sessions_count: {len(sessions)}")
                lines.append(f"sessions_sample: {sessions[:10]}")
                if sessions:
                    messages = backend.fetch_messages(sessions[0], limit=3)
                    lines.append(f"messages_count: {len(messages)}")
                    for msg in messages:
                        lines.append(f"message: {msg.sender!r} {msg.content[:80]!r} self={msg.is_self}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"connect_error: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"fatal_error: {type(exc).__name__}: {exc}")

    if getattr(sys, "frozen", False):
        out_dir = Path(sys.executable).resolve().parent
    else:
        out_dir = Path(__file__).resolve().parent
    out_path = out_dir / "wx_diagnose.txt"
    try:
        out_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass
    print("\n".join(lines))
    return 0


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        version = ".".join(str(x) for x in MIN_PYTHON)
        _fatal_message(
            APP_TITLE,
            f"当前 Python 版本过低：{sys.version.split()[0]}\n"
            f"请安装 Python {version} 或更高版本：\n"
            "https://www.python.org/downloads/",
        )
        return 1

    _set_windows_dpi_awareness()

    try:
        from crush_analyzer.logs import init_logging

        logger = init_logging()
        logger.info("程序启动，argv=%s", sys.argv)
    except Exception:
        logger = None

    if "--diagnose-wechat" in sys.argv:
        if logger:
            logger.info("进入微信诊断模式")
        return _diagnose_wechat()

    from crush_analyzer.ui.main_window import run_app

    run_app()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        log_path = _write_crash_log(exc)
        detail = f"{type(exc).__name__}: {exc}"
        if log_path:
            detail += f"\n\n详细日志已写入：\n{log_path}"
        _fatal_message(APP_TITLE, f"程序启动失败：\n\n{detail}")
        raise
