"""PyInstaller 打包脚本。

用法：
    python build_exe.py            # 自动 patch 版本 +1，然后打包
    python build_exe.py --no-bump  # 不自动迭代版本，直接打包

生成文件：
    dist/CrushChatAnalyzer_v<version>.exe
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from crush_analyzer.versioning import bump_patch, get_version


def main() -> int:
    root = Path(__file__).resolve().parent
    if "--no-bump" in sys.argv:
        version = get_version()
        print(f"使用当前版本：v{version}")
    else:
        version = bump_patch()
        print(f"版本已自动迭代：v{version}")

    name = f"CrushChatAnalyzer_v{version}"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        name,
        "--icon",
        str(root / "assets" / "icon.ico"),
        "--add-data",
        f"{root / 'assets' / 'icon.ico'}{os.pathsep}assets",
        "--add-data",
        f"{root / 'assets' / 'icon.png'}{os.pathsep}assets",
    ]
    # 打包微信自动化后端及其依赖。
    # 原版 wxauto 以及兼容实现 wechatauto（wechatauto-replica）都尝试收集。
    backend_packages = [
        "wxauto",
        "wechatauto",
        "uiautomation",
        "comtypes",
        "pyperclip",
        "PIL",
        "psutil",
        "colorama",
        "cryptography",
    ]
    collected = []
    for package in backend_packages:
        try:
            importlib.import_module(package)
        except Exception:
            continue
        cmd += ["--collect-all", package]
        collected.append(package)
    if collected:
        print("将一并打包的微信自动化相关包：", ", ".join(collected))
    else:
        print("未安装 wxauto / wechatauto，打包后将无法直接连接微信；导入聊天记录功能不受影响。")

    # pywin32 模块是 wechatauto / uiautomation 的运行时依赖，动态导入需要显式收集。
    for module in (
        "win32ui",
        "win32api",
        "win32con",
        "win32gui",
        "win32process",
        "win32clipboard",
        "pythoncom",
        "pywintypes",
        "win32com",
        "win32com.client",
    ):
        try:
            if importlib.util.find_spec(module):
                cmd += ["--hidden-import", module]
        except Exception:
            pass

    cmd.append(str(root / "main.py"))
    print("运行：", " ".join(cmd))
    try:
        code = subprocess.call(cmd, cwd=root)
    except FileNotFoundError:
        print("未找到 PyInstaller，请先运行：python -m pip install pyinstaller")
        return 1

    if code == 0:
        # 清理 PyInstaller 中间文件，保持项目文件夹干净。
        for temp in (root / f"{name}.spec", root / "build"):
            try:
                if temp.is_dir():
                    shutil.rmtree(temp, ignore_errors=True)
                elif temp.exists():
                    temp.unlink()
            except Exception:
                pass
        exe_path = root / "dist" / f"{name}.exe"
        print("打包完成：")
        print(exe_path)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
