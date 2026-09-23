"""微信接入适配层。

Windows 上优先尝试 `wxauto <https://github.com/cluic/wxauto>`_。
wxauto 是可选依赖；未安装时界面会提示安装命令，不影响聊天记录导入和分析。

不同 wxauto 版本 API 略有差异，因此这里用“方法探测 + 参数回退”的方式适配。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import importlib
import os
from pathlib import Path
import site
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .models import Message, parse_dt


class WeChatError(RuntimeError):
    pass


_WXAUTO_READY: Optional[bool] = None
_WXAUTO_MODULE: Any = None
_WXAUTO_MODULE_NAME: str = ""
_WXAUTO_VERSION: str = ""
_LAST_WXAUTO_ERROR: str = ""
_LAST_WXAUTO_SEARCHED: List[str] = []
_LAST_WXAUTO_SCAN_AT: float = 0.0

# 原版 wxauto 在部分新版 Python / 微信客户端上无法安装；
# 这里兼容 wechatauto（PyPI 包名 wechatauto-replica，模块名 wechatauto），
# 它的 WeChat / Chat API 与 wxauto 基本兼容。
WXAUTO_MODULES = ("wxauto", "wechatauto")


def _dedupe_paths(paths: Iterable[str]) -> List[str]:
    result: List[str] = []
    for path in paths:
        if not path:
            continue
        expanded = str(Path(path).expanduser())
        if expanded and expanded not in result and Path(expanded).exists():
            result.append(expanded)
    return result


def _python_site_packages_candidates() -> List[str]:
    """查找系统 Python 的 site-packages。

    exe 打包版运行时，sys.path 里通常没有用户后来 pip install 的 wxauto，
    这里尽量把系统 Python 的 site-packages 补回来。
    """
    candidates: List[str] = []

    for env_name in ("PYTHONPATH", "PYTHONHOME"):
        env_value = os.environ.get(env_name, "")
        for item in env_value.split(os.pathsep):
            if item:
                candidates.append(item)

    # 当前解释器/打包环境已有路径
    candidates.extend(sys.path)

    # 标准库 site 信息
    try:
        candidates.extend(site.getsitepackages())
    except Exception:  # noqa: BLE001
        pass
    try:
        candidates.append(site.getusersitepackages())
    except Exception:  # noqa: BLE001
        pass

    # 尝试调用 Windows 上的 py launcher / python，拿到真实系统 Python 的 site-packages。
    # 优先查 3.11 / 3.10，因为 wxauto 对 Python 3.13 的兼容性可能不好。
    py_launcher = _which("py")
    python_launcher = _which("python") or _which("python3")
    launcher_attempts: List[List[str]] = []
    if py_launcher:
        for version in ("-3.11", "-3.10", "-3.9", "-3"):
            launcher_attempts.append([py_launcher, version])
    if python_launcher:
        launcher_attempts.append([python_launcher])

    for launcher in launcher_attempts:
        try:
            proc = subprocess.run(
                launcher + ["-c", "import site; print(';'.join(site.getsitepackages()))"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
            )
            if proc.returncode == 0:
                for item in (proc.stdout or "").strip().split(";"):
                    if item:
                        candidates.append(item)
        except Exception:  # noqa: BLE001
            continue

    # 常见 Windows Python 安装目录
    roots: List[Path] = []
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        roots.append(Path(local_app) / "Programs" / "Python")
    for base in (Path("C:/Python"), Path("C:/Program Files/Python"), Path("D:/Python")):
        roots.append(base)
    roots.append(Path.home() / "AppData" / "Local" / "Programs" / "Python")
    for root in roots:
        if not root.exists():
            continue
        try:
            for python_exe in list(root.glob("Python*/python.exe")) + list(root.glob("python.exe")):
                candidates.append(str(python_exe.parent / "Lib" / "site-packages"))
                candidates.append(str(python_exe.parent / "Lib" / "site-packages"))
        except Exception:  # noqa: BLE001
            continue
    return _dedupe_paths(candidates)


def _which(name: str) -> str:
    import shutil

    return shutil.which(name) or ""


def _try_import_wxauto_module() -> tuple[Any, str, str, str]:
    """依次尝试 wxauto / wechatauto，返回 module, name, version, error。"""
    errors: List[str] = []
    for name in WXAUTO_MODULES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if not hasattr(module, "WeChat"):
            errors.append(f"{name}: 未找到 WeChat 类")
            continue
        version = getattr(module, "__version__", "") or getattr(module, "VERSION", "")
        return module, name, str(version or "未知"), ""
    return None, "", "", "; ".join(errors) if errors else "未找到 wxauto / wechatauto"


def prepare_external_wxauto(force: bool = False) -> bool:
    """尝试导入 wxauto 或 wechatauto；exe 版会补充系统 Python 的 site-packages。"""
    global _WXAUTO_READY, _WXAUTO_MODULE, _WXAUTO_MODULE_NAME, _WXAUTO_VERSION
    global _LAST_WXAUTO_ERROR, _LAST_WXAUTO_SEARCHED, _LAST_WXAUTO_SCAN_AT

    if _WXAUTO_MODULE is not None and not force:
        return True
    # 短时间内的重复检测直接复用上次失败结果，避免反复扫描导致启动变慢。
    if not force and _LAST_WXAUTO_SCAN_AT and (time.time() - _LAST_WXAUTO_SCAN_AT) < 5:
        return bool(_WXAUTO_MODULE is not None)
    _LAST_WXAUTO_SCAN_AT = time.time()

    module, name, version, error = _try_import_wxauto_module()
    if module is not None:
        _WXAUTO_MODULE = module
        _WXAUTO_MODULE_NAME = name
        _WXAUTO_VERSION = version
        _WXAUTO_READY = True
        _LAST_WXAUTO_ERROR = ""
        return True

    searched = _python_site_packages_candidates()
    _LAST_WXAUTO_SEARCHED = searched
    for path in searched:
        if path not in sys.path:
            sys.path.insert(0, path)
    importlib.invalidate_caches()

    module, name, version, error2 = _try_import_wxauto_module()
    if module is not None:
        _WXAUTO_MODULE = module
        _WXAUTO_MODULE_NAME = name
        _WXAUTO_VERSION = version
        _WXAUTO_READY = True
        _LAST_WXAUTO_ERROR = ""
        return True

    _WXAUTO_READY = False
    _LAST_WXAUTO_ERROR = error2 or error or "未找到 wxauto / wechatauto"
    return False


def wxauto_status(force: bool = False) -> Dict[str, Any]:
    """返回 wxauto / wechatauto 是否可导入及版本信息，供界面显示。"""
    global _WXAUTO_READY
    if force:
        _WXAUTO_READY = None
    installed = prepare_external_wxauto(force=force)
    if installed:
        return {
            "installed": True,
            "name": _WXAUTO_MODULE_NAME or "wxauto",
            "version": _WXAUTO_VERSION or "未知",
            "error": "",
            "frozen": bool(getattr(sys, "frozen", False)),
            "python": sys.executable,
            "search_paths": list(_LAST_WXAUTO_SEARCHED),
        }
    return {
        "installed": False,
        "name": "",
        "version": "",
        "error": _LAST_WXAUTO_ERROR or "未找到 wxauto / wechatauto",
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.executable,
        "search_paths": list(_LAST_WXAUTO_SEARCHED),
    }


def wxauto_diagnostics() -> str:
    status = wxauto_status(force=True)
    lines = [
        f"微信自动化后端已安装：{status.get('installed')}",
        f"后端名称：{status.get('name') or '无'}",
        f"版本：{status.get('version') or '未知'}",
        f"当前解释器：{status.get('python')}",
        f"是否为打包 exe：{status.get('frozen')}",
        "",
        "导入错误：",
        status.get("error") or "无",
        "",
        "已搜索的 site-packages：",
    ]
    for path in status.get("search_paths") or []:
        lines.append(f"  {path}")
    lines.extend(
        [
            "",
            "说明：",
            "  程序会优先使用 wxauto；如果当前 Python 版本装不上 wxauto，",
            "  会自动尝试 wechatauto（包名 wechatauto-replica）。",
            "",
            "解决建议：",
            "1. 源码版：python -m pip install wxauto",
            "   或：python -m pip install wechatauto-replica --no-deps",
            "       python -m pip install uiautomation pyperclip Pillow psutil colorama pywin32 cryptography",
            "2. exe 版：先安装自动化依赖，再执行 打包成exe.bat 重新打包。",
        ]
    )
    return "\n".join(lines)


def _call_first(obj: Any, names: Sequence[str], *args: Any, **kwargs: Any) -> Any:
    """调用对象上第一个存在的方法。支持自动忽略不接受的参数。"""
    for name in names:
        method = getattr(obj, name, None)
        if not callable(method):
            continue
        try:
            return method(*args, **kwargs)
        except TypeError:
            # 尝试去掉关键字参数、位置参数，兼容不同版本签名
            attempts: List[Callable[[], Any]] = [
                lambda m=method, a=args: m(*a),
                lambda m=method, k=kwargs: m(**k),
                lambda m=method: m(),
            ]
            for attempt in attempts:
                try:
                    return attempt()
                except TypeError:
                    continue
            raise
    raise AttributeError(f"对象没有可调用的方法：{', '.join(names)}")


def _normalize_session_item(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    for attr in ("name", "nickname", "remark", "nick_name", "NickName", "title", "who"):
        value = getattr(item, attr, None)
        if value:
            return str(value).strip()
    if isinstance(item, dict):
        for key in ("name", "nickname", "remark", "NickName", "title", "who"):
            if item.get(key):
                return str(item[key]).strip()
    return str(item).strip()


def _normalize_message_item(item: Any, chat: str = "") -> Optional[Message]:
    if item is None:
        return None
    if isinstance(item, Message):
        return item
    sender = ""
    content = ""
    timestamp: Any = None
    is_self = False
    msg_id = ""
    raw: Dict[str, Any] = {}

    if isinstance(item, str):
        content = item.strip()
        if not content:
            return None
        return Message(sender=chat or "对方", content=content, timestamp=None, is_self=False)

    # 常见 wxauto Message 对象
    for attr in ("sender", "Sender", "from_user", "fromUser", "nickname", "who"):
        value = getattr(item, attr, None)
        if value:
            sender = str(value).strip()
            break
    for attr in ("content", "Content", "text", "msg", "message"):
        value = getattr(item, attr, None)
        if value is not None:
            content = str(value).strip()
            break
    for attr in ("time", "Time", "timestamp", "create_time", "CreateTime"):
        value = getattr(item, attr, None)
        if value is not None:
            timestamp = value
            break
    for attr in ("id", "ID", "msg_id", "MsgId", "hash"):
        value = getattr(item, attr, None)
        if value:
            msg_id = str(value)
            break
    for attr in ("is_self", "isSelf", "is_sender", "IsSender", "from_me"):
        value = getattr(item, attr, None)
        if value is not None:
            is_self = bool(value)
            break
    for attr in ("type", "info", "attr"):
        value = getattr(item, attr, None)
        if value:
            raw[attr] = value

    if isinstance(item, dict):
        sender = sender or str(item.get("sender") or item.get("from") or item.get("nickname") or "").strip()
        content = content or str(item.get("content") or item.get("msg") or item.get("text") or "").strip()
        timestamp = timestamp or item.get("time") or item.get("timestamp") or item.get("CreateTime")
        msg_id = msg_id or str(item.get("id") or item.get("msg_id") or "")
        if item.get("is_self") is not None:
            is_self = bool(item["is_self"])
        raw.update(item)

    if not content:
        return None
    return Message(
        sender=sender or chat or "对方",
        content=content,
        timestamp=parse_dt(timestamp),
        is_self=is_self,
        message_id=msg_id or None,
        raw=raw,
    )


class WxautoBackend:
    """wxauto 后端。所有方法在未连接时抛 WeChatError。"""

    def __init__(self) -> None:
        self._wx: Any = None
        self._db: Any = None
        self._db_self: Dict[str, Any] = {}
        self._version = ""
        self._backend_name = "wxauto"

    @property
    def connected(self) -> bool:
        return self._wx is not None or self._db is not None

    @property
    def name(self) -> str:
        return self._backend_name or "wxauto"

    @property
    def version(self) -> str:
        return self._version

    def _connect_db(self) -> bool:
        """尝试使用 wechatauto 的本地数据库读取聊天记录。

        数据库模式不会主动弹出/激活微信窗口，适合导入和自动回复轮询。
        """
        status = wxauto_status(force=False)
        if status.get("name") != "wechatauto":
            return False
        try:
            from wechatauto.db import WeChatDB  # type: ignore

            db = WeChatDB()
            self._db_self = db.get_self_info() or {}
            # 触发一次读写，确认数据库可用。
            db.get_sessions(limit=1)
            db.get_messages(str(self._db_self.get("username") or ""), limit=1)
            self._db = db
            self._backend_name = "wechatauto-db"
            return True
        except Exception:
            self._db = None
            self._db_self = {}
            return False

    def _ensure_gui(self):
        """按需初始化 GUI 驱动，只有发送消息等操作才需要。"""
        if self._wx is not None:
            return self._wx
        if _WXAUTO_MODULE is None:
            prepare_external_wxauto(force=True)
        module = _WXAUTO_MODULE
        if module is None:
            raise WeChatError("没有找到可用的微信自动化后端。")
        wechat_cls = getattr(module, "WeChat")
        self._wx = wechat_cls()
        return self._wx

    def _db_display_name(self, username: str) -> str:
        if not username:
            return ""
        if username == "filehelper":
            return "文件传输助手"
        try:
            name = self._db.get_nickname(username) if self._db else ""
        except Exception:
            name = ""
        if name and name != username:
            return str(name)
        try:
            group_name = self._db.group_id_to_name(username) if self._db else ""
        except Exception:
            group_name = ""
        return str(group_name or name or username)

    def _resolve_db_username(self, chat: str) -> str:
        chat = (chat or "").strip()
        if not self._db or not chat:
            return chat
        if chat in ("文件传输助手", "filehelper"):
            return "filehelper"
        try:
            wxid = self._db.username_by_nickname(chat)
            if wxid:
                return str(wxid)
        except Exception:
            pass
        try:
            chatroom = self._db.group_name_to_id(chat)
            if chatroom:
                return str(chatroom)
        except Exception:
            pass
        try:
            hits = self._db.search_contact(chat) or []
            for hit in hits:
                if chat in (hit.get("nick_name"), hit.get("remark")):
                    return str(hit.get("username") or chat)
        except Exception:
            pass
        # 群聊数据库里没有精确名字时，尝试用会话列表里的用户名兜底。
        try:
            for row in self._db.get_sessions(limit=300) or []:
                username = str(row.get("username") or "")
                if username and self._db_display_name(username) == chat:
                    return username
        except Exception:
            pass
        return chat

    def _db_row_to_message(self, row: Dict[str, Any], chat: str, username: str = "") -> Message:
        sender_id = row.get("sender_id")
        self_wxid = str(self._db_self.get("username") or "")
        sender_username = str(row.get("sender_username") or "")
        # 当前微信数据库里：sender_id/sender_username 为 1 或 2 代表自己；
        # 群聊中其他成员是递增数字 ID，私聊中对方是对方的数字 ID。
        is_self = (
            str(sender_id) in ("1", "2")
            or sender_username in ("1", "2")
            or bool(self_wxid and sender_username == self_wxid)
        )
        content = row.get("content") or row.get("summary") or ""
        mtype_name = str(row.get("type") or "")
        try:
            from wechatauto.db import WeChatDB  # type: ignore

            if not mtype_name:
                mtype_name = str(WeChatDB._msg_type_name(row.get("local_type")) or "")
            if isinstance(content, bytes):
                content = WeChatDB._friendly_content(content, mtype_name or "未知消息")
            else:
                content = str(content)
                if mtype_name and mtype_name not in ("文本", "系统消息") and (
                    not content.strip() or content.lstrip().startswith("<")
                ):
                    content = f"[{mtype_name}]"
        except Exception:
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8", errors="replace")
                except Exception:
                    content = "[媒体消息]"
            content = str(content)
        is_group = username.endswith("@chatroom") or str(row.get("username") or "").endswith("@chatroom")
        if is_self:
            sender = "我"
        else:
            sender_name = str(row.get("sender_username") or "").strip()
            if is_group and sender_name not in ("", "1", "2"):
                sender = sender_name
            else:
                sender = chat or "对方"
        raw = dict(row)
        if username:
            raw["_chat_username"] = username
        return Message(
            sender=sender,
            content=str(content),
            timestamp=parse_dt(row.get("create_time")),
            is_self=bool(is_self),
            message_id=str(row.get("local_id") or row.get("sort_seq") or ""),
            raw=raw,
        )

    def download_media_for_message(self, msg: Message) -> Optional[str]:
        """下载消息对应的图片/语音文件，供 OCR / 语音转文字使用。"""
        if self._db is None or not msg.raw:
            return None
        username = str(msg.raw.get("_chat_username") or "")
        local_id = msg.raw.get("local_id")
        if not username or local_id is None:
            return None
        try:
            from wechatauto.media import MediaDownloader  # type: ignore

            downloader = MediaDownloader(self._db)
            content = msg.content or ""
            if "[图片]" in content:
                return downloader.download_image(username, int(local_id))
            if "[语音]" in content:
                return downloader.download_voice(username, int(local_id))
        except Exception:
            return None
        return None

    @staticmethod
    def _force_foreground(hwnd: int) -> None:
        """尽量把微信窗口强制切到前台，避免剪贴板/按键发到本程序自己。"""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            fg = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            target_tid = user32.GetWindowThreadProcessId(hwnd, None)
            try:
                if fg_tid and target_tid:
                    user32.AttachThreadInput(fg_tid, target_tid, True)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if fg_tid and target_tid:
                    user32.AttachThreadInput(fg_tid, target_tid, False)
            # 置顶再取消置顶，强制 Windows 重新排序。
            HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
            SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        except Exception:
            pass

    @staticmethod
    def _find_wechat_render_window(main_hwnd: int) -> int:
        """查找微信 QtQuick 渲染子窗口，坐标比例应以它为准。"""
        try:
            import win32gui  # type: ignore
        except Exception:
            return main_hwnd
        best = {"area": 0, "hwnd": 0}

        def _callback(hwnd, _extra):
            try:
                cls = win32gui.GetClassName(hwnd) or ""
                if not cls.startswith("MMUIRenderSubWindow"):
                    return True
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                area = max(0, right - left) * max(0, bottom - top)
                if area > best["area"]:
                    best["area"] = area
                    best["hwnd"] = hwnd
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(main_hwnd, _callback, None)
        except Exception:
            pass
        return int(best["hwnd"] or main_hwnd)

    def _find_wechat_main_window(self) -> int:
        """通过 Windows API 查找微信主窗口，不依赖 OCR / winsdk。"""
        try:
            import psutil  # type: ignore
            import win32gui  # type: ignore
            import win32process  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise WeChatError(f"缺少 Windows 自动化组件：{exc}") from exc

        pids = set()
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in ("weixin.exe", "wechat.exe"):
                pids.add(proc.pid)
        if not pids:
            raise WeChatError("没有找到正在运行的微信 PC 版进程。")

        candidates: List[tuple[int, int]] = []

        def _callback(hwnd, _extra):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in pids:
                    return True
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                area = max(0, right - left) * max(0, bottom - top)
                if area > 40000:
                    candidates.append((area, hwnd))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_callback, None)
        candidates.sort(key=lambda item: item[0], reverse=True)
        # 优先选择内部有 MMUIRenderSubWindow 渲染子窗口的窗口。
        for _area, hwnd in candidates:
            if self._find_wechat_render_window(hwnd) != hwnd:
                return int(hwnd)
        if candidates:
            return int(candidates[0][1])
        raise WeChatError("没有找到微信主窗口，请确认微信已登录且窗口未最小化。")

    @staticmethod
    def _set_clipboard_text(text: str) -> None:
        import win32clipboard  # type: ignore
        import win32con  # type: ignore

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def _keypress(vk: int) -> None:
        import win32api  # type: ignore
        import win32con  # type: ignore

        win32api.keybd_event(vk, 0, 0, 0)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)

    @classmethod
    def _ctrl_keypress(cls, vk: int) -> None:
        import win32api  # type: ignore
        import win32con  # type: ignore

        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(vk, 0, 0, 0)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _send_via_keyboard(self, chat: str, text: str) -> None:
        """不依赖 winsdk 的发送方式：聚焦微信，搜索联系人，粘贴并发送。"""
        import win32con  # type: ignore
        import win32gui  # type: ignore

        main_hwnd = self._find_wechat_main_window()
        render_hwnd = self._find_wechat_render_window(main_hwnd)
        self._force_foreground(main_hwnd)
        time.sleep(0.45)

        # 点击微信聊天列表上方的搜索框，避免 Ctrl+F 未聚焦时把联系人名粘进聊天输入框。
        import win32api  # type: ignore

        left, top, right, bottom = win32gui.GetWindowRect(render_hwnd)
        width = max(1, right - left)
        height = max(1, bottom - top)
        # 微信 4.1：搜索框位于左侧聊天列表顶部，约 (0.20w, 0.09h)。
        search_cx = left + int(width * 0.20)
        search_cy = top + int(height * 0.09)
        try:
            win32api.SetCursorPos((search_cx, search_cy))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception:
            pass
        time.sleep(0.35)
        self._ctrl_keypress(ord("A"))
        self._keypress(win32con.VK_DELETE)
        self._set_clipboard_text(chat)
        self._ctrl_keypress(ord("V"))
        time.sleep(0.85)
        self._keypress(win32con.VK_RETURN)
        time.sleep(0.85)

        # 点击聊天输入区域，确保焦点在输入框而不是侧栏/搜索框。
        try:
            import win32api  # type: ignore

            left, top, right, bottom = win32gui.GetWindowRect(render_hwnd)
            click_x = left + int((right - left) * 0.65)
            click_y = bottom - 58
            win32api.SetCursorPos((click_x, click_y))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.25)
        except Exception:
            pass

        # 粘贴消息并发送。
        self._set_clipboard_text(text)
        self._ctrl_keypress(ord("V"))
        time.sleep(0.25)
        self._keypress(win32con.VK_RETURN)
        time.sleep(0.25)

    def connect(self) -> str:
        status = wxauto_status(force=True)
        if not status["installed"]:
            detail = (status.get("error") or "未找到 wxauto / wechatauto").strip()
            raise WeChatError(
                "没有检测到可用的微信自动化后端。\n"
                f"导入错误：{detail}\n\n"
                "源码版可执行：python -m pip install wxauto\n"
                "如果 wxauto 装不上，也可以安装兼容后端：\n"
                "  python -m pip install wechatauto-replica --no-deps\n"
                "  python -m pip install uiautomation pyperclip Pillow psutil colorama pywin32 cryptography\n"
                "并确保 Windows 微信 PC 版已经登录且窗口未最小化。"
            )
        self._version = str(status.get("version") or "")
        self._backend_name = str(status.get("name") or "wxauto")

        # 优先使用本地数据库读取模式：不会反复弹出/激活微信窗口。
        if self._connect_db():
            return f"已连接微信（{self._backend_name}，数据库读取模式）"

        try:
            self._ensure_gui()
            return f"已连接微信（{self._backend_name} {self._version or '未知版本'}）"
        except Exception as exc:  # noqa: BLE001
            self._wx = None
            raise WeChatError(
                f"已找到微信自动化后端，但连接微信失败：{exc}\n"
                "请确认微信 PC 版已登录、窗口未最小化，并且后端版本与微信版本兼容。"
            ) from exc

    def disconnect(self) -> None:
        self._wx = None
        self._db = None
        self._db_self = {}

    def _ensure(self) -> Any:
        if self._wx is None:
            raise WeChatError("尚未连接微信。")
        return self._wx

    def list_sessions(self) -> List[str]:
        # 数据库读取模式：直接读取本地数据库，不激活微信窗口。
        if self._db is not None:
            names: List[str] = []
            try:
                rows = self._db.get_sessions(limit=300) or []
            except Exception:
                rows = []
            for row in rows:
                username = str(row.get("username") or "")
                name = self._db_display_name(username) or username
                if name and name not in names:
                    names.append(name)
            return names

        wx = self._ensure_gui()
        raw = _call_first(
            wx,
            ("GetSessionList", "GetAllSession", "GetSession", "GetContactList", "GetSessionList"),
        )
        if raw is None:
            return []
        if isinstance(raw, dict):
            raw = list(raw.keys())
        if not isinstance(raw, (list, tuple, set)):
            raw = [raw]
        names: List[str] = []
        for item in raw:
            name = _normalize_session_item(item)
            if name and name not in names:
                names.append(name)
        return names

    def _switch_chat(self, chat: str) -> None:
        wx = self._ensure_gui()
        if not chat:
            return
        method = getattr(wx, "ChatWith", None)
        if callable(method):
            try:
                method(chat)
            except Exception:
                # 切换失败不阻断后续读取，可能是当前会话已打开
                pass

    def fetch_messages(self, chat: str = "", limit: int = 200) -> List[Message]:
        # 数据库读取模式：根据会话名解析 wxid，然后直接从本地数据库读取。
        if self._db is not None:
            username = self._resolve_db_username(chat)
            try:
                rows = self._db.get_messages(username, limit=max(1, int(limit or 200))) or []
            except Exception as exc:  # noqa: BLE001
                raise WeChatError(f"读取微信数据库失败：{exc}") from exc
            # get_messages 通常按时间倒序返回，这里翻转为旧→新，方便分析。
            rows = list(reversed(rows))
            return [self._db_row_to_message(row, chat, username) for row in rows]

        wx = self._ensure_gui()
        if chat:
            self._switch_chat(chat)
        raw = None
        for args in ((chat,), ()):
            try:
                raw = _call_first(wx, ("GetAllMessage", "GetMessages", "GetHistoryMessage"), *args)
                break
            except Exception:
                continue
        if raw is None:
            try:
                raw = _call_first(wx, ("GetListenMessage", "GetNewMessage"))
            except Exception:
                raw = []
        if isinstance(raw, dict):
            raw = list(raw.values())
        if raw is None:
            raw = []
        if not isinstance(raw, (list, tuple, set)):
            raw = [raw]
        messages = [_normalize_message_item(item, chat=chat) for item in raw]
        messages = [m for m in messages if m is not None]
        if limit and len(messages) > limit:
            messages = messages[-limit:]
        return messages

    def send_message(self, chat: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            raise WeChatError("不能发送空消息。")

        # 首选 Win32 键盘/剪贴板发送：不需要 winsdk，适合数据库读取模式。
        last_error: Optional[Exception] = None
        try:
            search_name = chat
            if self._db is not None:
                username = self._resolve_db_username(chat)
                search_name = self._db_display_name(username) or chat
            self._send_via_keyboard(search_name, text)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc

        # 兜底：原 GUI 后端（如果用户安装了原版 wxauto）。
        try:
            wx = self._ensure_gui()
            attempts = [
                lambda: getattr(wx, "SendMsg")(text, chat),
                lambda: getattr(wx, "SendMsg")(msg=text, who=chat),
                lambda: getattr(wx, "SendMsg")(who=chat, msg=text),
                lambda: getattr(wx, "SendMsg")(text),
            ]
            for attempt in attempts:
                try:
                    attempt()
                    return
                except TypeError as exc:
                    last_error = exc
                    continue
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue
        except Exception as exc:  # noqa: BLE001
            last_error = last_error or exc
        raise WeChatError(f"发送微信消息失败：{last_error}")

    def get_current_chat(self) -> str:
        if self._db is not None:
            return ""
        wx = self._ensure_gui()
        for name in ("CurrentChat", "GetCurrentChat", "CurrentSession"):
            value = getattr(wx, name, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if value:
                return _normalize_session_item(value)
        return ""


class NullBackend:
    """占位后端，用于在未安装 wxauto 时保持界面结构。"""

    name = "未接入"

    @property
    def connected(self) -> bool:
        return False

    @property
    def version(self) -> str:
        return ""

    def connect(self) -> str:
        status = wxauto_status(force=True)
        detail = (status.get("error") or "未找到 wxauto").strip()
        raise WeChatError(
            "当前环境未检测到可用的 wxauto。\n"
            f"导入错误：{detail}\n\n"
            "源码版：python -m pip install wxauto\n"
            "exe 版：需要先安装 wxauto 后重新执行 打包成exe.bat，"
            "或使用 启动.bat 运行源码版。\n"
            "如果只想分析聊天记录，可以直接导入 txt/csv/json 文件。"
        )

    def disconnect(self) -> None:
        return None

    def list_sessions(self) -> List[str]:
        return []

    def fetch_messages(self, chat: str = "", limit: int = 200) -> List[Message]:
        return []

    def send_message(self, chat: str, text: str) -> None:
        raise WeChatError("尚未接入微信，无法发送消息。")

    def get_current_chat(self) -> str:
        return ""


def create_backend(force_wxauto: bool = False) -> WxautoBackend | NullBackend:
    status = wxauto_status()
    if status["installed"] or force_wxauto:
        return WxautoBackend()
    return NullBackend()
