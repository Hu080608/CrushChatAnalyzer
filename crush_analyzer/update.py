"""GitHub Releases 自动更新。

仅支持 PyInstaller 打包后的 exe 版：
1. 从 GitHub 最新 Release 读取版本号和 exe 下载地址；
2. 下载新 exe 到临时目录；
3. 生成一个等待当前进程退出的 bat；
4. 启动 bat 替换 exe 并重新启动程序。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
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
        notes=str(release.get("body") or ""),
    )


def download_update(info: UpdateInfo, progress=None, timeout: int = 180) -> Path:
    suffix = Path(info.asset_name).suffix or ".exe"
    fd, raw_path = tempfile.mkstemp(prefix="CrushChatAnalyzer_update_", suffix=suffix)
    os.close(fd)
    dest = Path(raw_path)
    request = urllib.request.Request(
        info.download_url,
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    downloaded = 0
    logger.info("开始下载更新: %s -> %s", info.download_url, dest)
    with urlopen(request, timeout=timeout) as response, dest.open("wb") as fh:
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
    logger.info("更新下载完成: %s (%s bytes)", dest, downloaded)
    return dest


def apply_update(new_exe: str | Path, target_exe: Optional[str | Path] = None) -> None:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("源码版不支持自动替换更新，请使用 git pull。")
    target = Path(target_exe or sys.executable).resolve()
    new_path = Path(new_exe).resolve()
    script = Path(tempfile.gettempdir()) / f"crush_chat_analyzer_update_{os.getpid()}.bat"
    content = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        ":wait\r\n"
        f'copy /Y "{new_path}" "{target}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  ping 127.0.0.1 -n 2 >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'start "" "{target}"\r\n'
        'del "%~f0" >nul 2>&1\r\n'
    )
    script.write_text(content, encoding="utf-8", newline="")
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        ["cmd", "/c", str(script)],
        creationflags=creationflags,
        close_fds=True,
    )
