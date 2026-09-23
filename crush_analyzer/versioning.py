"""版本号自动迭代工具。"""
from __future__ import annotations

import re
from pathlib import Path


VERSION_FILE = Path(__file__).with_name("version.py")
VERSION_RE = re.compile(r'__version__\s*=\s*["\'](\d+)\.(\d+)\.(\d+)["\']')


def get_version() -> str:
    text = VERSION_FILE.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        return "0.0.0"
    return ".".join(match.groups())


def bump_patch() -> str:
    """patch +1，并写回 version.py。返回新版本号。"""
    text = VERSION_FILE.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise RuntimeError("version.py 中没有找到 __version__ = 'x.y.z'")
    major, minor, patch = (int(x) for x in match.groups())
    new_version = f"{major}.{minor}.{patch + 1}"
    new_text = VERSION_RE.sub(f'__version__ = "{new_version}"', text, count=1)
    VERSION_FILE.write_text(new_text, encoding="utf-8")
    return new_version
