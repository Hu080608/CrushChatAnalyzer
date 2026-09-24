"""PyInstaller 打包脚本。

用法：
    python build_exe.py                 # 默认 patch +1（问题修复）
    python build_exe.py --bump minor    # 新增功能：minor +1，patch 归零
    python build_exe.py --bump major    # 不兼容变更：major +1，minor / patch 归零
    python build_exe.py --no-bump       # 不自动迭代版本，直接打包

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

from crush_analyzer.versioning import bump_major, bump_minor, bump_patch, get_version


def main() -> int:
    root = Path(__file__).resolve().parent
    args = sys.argv[1:]
    bump_type = "patch"
    if "--no-bump" in args:
        version = get_version()
        print(f"使用当前版本：v{version}")
    else:
        if "--bump" in args:
            index = args.index("--bump")
            if index + 1 < len(args):
                bump_type = args[index + 1].strip().lower()
            else:
                print("--bump 需要指定 major / minor / patch")
                return 2
        elif any(arg.startswith("--bump=") for arg in args):
            bump_type = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--bump=")).strip().lower()
        bumpers = {"major": bump_major, "minor": bump_minor, "patch": bump_patch}
        if bump_type not in bumpers:
            print("不支持的版本类型：", bump_type, "可选：major / minor / patch")
            return 2
        version = bumpers[bump_type]()
        print(f"版本已自动迭代（{bump_type}）：v{version}")

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
        "certifi",
        "zstandard",
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
