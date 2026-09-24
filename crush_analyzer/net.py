"""网络请求 SSL 上下文工具。

优先使用 certifi 的 CA 证书；PyInstaller 打包后会显式收集 certifi，
避免出现 Windows 上 ``CERTIFICATE_VERIFY_FAILED``。
"""
from __future__ import annotations

import ssl
from typing import Optional


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            # 最后兜底：部分 Windows 环境缺少 CA，自动更新不应因此完全不可用。
            return ssl._create_unverified_context()


def urlopen(request, timeout: int = 30, context: Optional[ssl.SSLContext] = None):
    import urllib.request

    return urllib.request.urlopen(request, timeout=timeout, context=context or ssl_context())
