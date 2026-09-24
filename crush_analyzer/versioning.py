"""版本号自动迭代工具。

遵循语义化版本：

* major：不兼容变更，minor / patch 归零
* minor：向后兼容的新功能，patch 归零
* patch：向后兼容的问题修复
"""
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


def _write_version(major: int, minor: int, patch: int) -> str:
    text = VERSION_FILE.read_text(encoding="utf-8")
    if not VERSION_RE.search(text):
        raise RuntimeError("version.py 中没有找到 __version__ = 'x.y.z'")
    new_version = f"{major}.{minor}.{patch}"
    new_text = VERSION_RE.sub(f'__version__ = "{new_version}"', text, count=1)
    VERSION_FILE.write_text(new_text, encoding="utf-8")
    return new_version


def _current_parts() -> tuple[int, int, int]:
    text = VERSION_FILE.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise RuntimeError("version.py 中没有找到 __version__ = 'x.y.z'")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def bump_major() -> str:
    """不兼容变更：主版本 +1，次版本和修订号归零。"""
    major, _minor, _patch = _current_parts()
    return _write_version(major + 1, 0, 0)


def bump_minor() -> str:
    """向后兼容的新功能：次版本 +1，修订号归零。"""
    major, minor, _patch = _current_parts()
    return _write_version(major, minor + 1, 0)


def bump_patch() -> str:
    """问题修复：修订号 +1。"""
    major, minor, patch = _current_parts()
    return _write_version(major, minor, patch + 1)
