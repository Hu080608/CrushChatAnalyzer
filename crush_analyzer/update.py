"""GitHub Releases 自动更新。

仅支持 PyInstaller 打包后的 exe 版：
1. 从 GitHub 最新 Release 读取版本号和 exe 下载地址；
2. 下载新 exe 到临时目录；
3. 下载完成后启动新 exe 作为更新助手；
4. 更新助手等待旧进程退出，替换 exe 并重新启动。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Optional
import urllib.error
import urllib.request

from .logs import get_logger
from .net import urlopen

GITHUB_REPO = "Hu080608/CrushChatAnalyzer"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
USER_AGENT = "CrushChatAnalyzer-Update"
logger = get_logger("update")


@dataclass
class UpdateInfo:
    version: str
    tag: str
    release_url: str
    download_url: str
    asset_name: str
    size: int = 0
    notes: str = ""


def parse_version(value: str) -> tuple[int, ...]:
    text = str(value or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", text)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts[:4])


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def fetch_latest_release(timeout: int = 15) -> Dict[str, Any]:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    logger.info("检查 GitHub 最新 release: %s", LATEST_RELEASE_API)
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    logger.info("最新 release: %s", data.get("tag_name"))
    return data


def pick_exe_asset(release: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    assets = release.get("assets") or []
    candidates = [
        a for a in assets
        if str(a.get("name") or "").lower().endswith(".exe")
        and "crushchatanalyzer" in str(a.get("name") or "").lower()
    ]
    if not candidates:
        return None
    tag = str(release.get("tag_name") or "").lstrip("vV")
    for asset in candidates:
        if tag and tag in str(asset.get("name") or ""):
            return asset
    return candidates[0]


def check_for_update(current_version: str, timeout: int = 15) -> Optional[UpdateInfo]:
    release = fetch_latest_release(timeout=timeout)
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        return None
    latest_version = tag.lstrip("vV")
    if not is_newer(latest_version, current_version):
        logger.info("当前版本 %s 已是最新（最新 %s）", current_version, latest_version)
        return None
    asset = pick_exe_asset(release)
    if not asset or not asset.get("browser_download_url"):
        return None
    return UpdateInfo(
        version=latest_version,
        tag=tag,
        release_url=str(release.get("html_url") or RELEASES_PAGE),
        download_url=str(asset["browser_download_url"]),
        asset_name=str(asset.get("name") or f"CrushChatAnalyzer_v{latest_version}.exe"),
        size=int(asset.get("size") or 0),
        notes=str(release.get("body") or ""),
    )


def _candidate_urls(url: str) -> list[str]:
    """GitHub 直连失败时依次尝试常见加速镜像。"""
    prefixes = [
        "https://ghfast.top/",
        "https://ghproxy.net/",
        "https://gh-proxy.com/",
    ]
    urls: list[str] = []
    for prefix in prefixes:
        candidate = f"{prefix}{url}"
        if candidate not in urls:
            urls.append(candidate)
    if url not in urls:
        urls.append(url)
    return urls


def update_dir() -> Path:
    from .config import app_home

    path = app_home() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_update(info: UpdateInfo, progress=None, timeout: int = 180) -> Path:
    """下载更新到用户可见的 updates 目录，失败时自动切换镜像并重试。"""
    dest = update_dir() / info.asset_name
    part = dest.with_suffix(dest.suffix + ".part")
    last_error: Optional[Exception] = None
    for candidate in _candidate_urls(info.download_url):
        for attempt in range(1, 3):
            downloaded = 0
            logger.info("开始下载更新（第 %s 次，来源 %s） -> %s", attempt, candidate, dest)
            try:
                request = urllib.request.Request(
                    candidate,
                    headers={"User-Agent": USER_AGENT},
                    method="GET",
                )
                with urlopen(request, timeout=min(timeout, 90)) as response, part.open("wb") as fh:
                    total = int(response.headers.get("Content-Length") or 0)
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            try:
                                progress(downloaded, total)
                            except Exception:
                                pass
                actual = part.stat().st_size
                if info.size and actual != info.size:
                    raise RuntimeError(f"下载文件大小不匹配：期望 {info.size}，实际 {actual}")
                if actual < 1024 * 1024:
                    raise RuntimeError(f"下载文件过小：{actual} bytes")
                with part.open("rb") as fh:
                    if fh.read(2) != b"MZ":
                        raise RuntimeError("下载到的不是有效的 Windows exe")
                os.replace(part, dest)
                logger.info("更新下载完成: %s (%s bytes)", dest, actual)
                return dest
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("更新下载失败 source=%s attempt=%s: %s", candidate, attempt, exc)
                try:
                    part.unlink()
                except Exception:
                    pass
                time.sleep(1.0)
    raise RuntimeError(
        f"自动下载更新失败：{last_error}"
        + "\n\n可以手动打开 Release 页面下载：\n"
        + info.release_url
    )


def _wait_for_process_exit(pid: int, timeout: int = 120) -> None:
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, int(pid))
            if handle:
                try:
                    kernel32.WaitForSingleObject(handle, timeout * 1000)
                finally:
                    kernel32.CloseHandle(handle)
            else:
                time.sleep(3)
        else:
            time.sleep(3)
    except Exception:
        time.sleep(3)


def apply_update_worker(target_exe: str, new_exe: str, old_pid: str | int) -> int:
    """由新版本 exe 以 ``--apply-update`` 启动，等待旧进程退出后替换并重启。"""
    target = Path(target_exe).resolve()
    new_path = Path(new_exe).resolve()
    logger.info("更新助手启动：等待旧进程 %s 退出；target=%s new=%s", old_pid, target, new_path)
    try:
        _wait_for_process_exit(int(old_pid))
    except Exception:
        time.sleep(3)

    last_error: Optional[Exception] = None
    for attempt in range(1, 91):
        temp_target = target.parent / (target.name + ".update_tmp")
        try:
            if not new_path.exists():
                raise RuntimeError(f"更新文件不存在：{new_path}")
            # 先复制到目标目录，再 os.replace。
            # 这样即使下载目录和目标 exe 不在同一个磁盘，也不会报 WinError 17。
            try:
                temp_target.unlink()
            except Exception:
                pass
            shutil.copyfile(new_path, temp_target)
            os.replace(temp_target, target)
            logger.info("更新替换成功：%s -> %s（经 %s）", new_path, target, temp_target)
            subprocess.Popen([str(target)], close_fds=True, cwd=str(target.parent))
            try:
                new_path.unlink()
            except Exception:
                pass
            return 0
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            try:
                temp_target.unlink()
            except Exception:
                pass
            if attempt == 1 or attempt % 10 == 0:
                logger.warning("替换更新文件失败 attempt=%s: %s", attempt, exc)
            time.sleep(1.0)

    detail = f"自动更新失败：{last_error}\n文件未替换。\n新版本文件：{new_path}\n旧版本文件：{target}"
    logger.error(detail)
    try:
        error_file = update_dir() / "update_error.log"
        error_file.write_text(detail, encoding="utf-8")
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, detail, "Crush Chat Analyzer 更新失败", 0x10)
    except Exception:
        pass
    return 1


def apply_update(new_exe: str | Path, target_exe: Optional[str | Path] = None) -> None:
    """启动新版本 exe 作为更新助手，不再使用可见 BAT 窗口。"""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("源码版不支持自动替换更新，请使用 git pull。")
    target = Path(target_exe or sys.executable).resolve()
    new_path = Path(new_exe).resolve()
    if not new_path.exists():
        raise RuntimeError(f"更新文件不存在：{new_path}")
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    cmd = [str(new_path), "--apply-update", str(target), str(new_path), str(os.getpid())]
    logger.info("启动更新助手：%s", cmd)
    subprocess.Popen(cmd, close_fds=True, creationflags=creationflags)
