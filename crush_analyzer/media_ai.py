"""图片 / 语音内容识别（可选）。

使用任意 OpenAI 兼容接口：

* 图片：``/chat/completions`` + 视觉模型
* 语音：``/audio/transcriptions`` + 语音转文字模型

未配置时完全不影响主程序，聊天里只显示 [图片] / [语音] 标签。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import urllib.error
import urllib.request
import uuid

from .config import AppConfig
from .models import Message


def _base_url(config: AppConfig) -> str:
    return (config.media_ai_base_url or config.base_url or "https://api.deepseek.com").rstrip("/")


def _api_key(config: AppConfig) -> str:
    return (config.media_ai_api_key or config.api_key or "").strip()


def _post_json(url: str, payload: Dict[str, Any], api_key: str, timeout: int = 120) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def _encode_multipart(fields: Dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----CrushChatAnalyzer" + uuid.uuid4().hex
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        lines.append(str(value).encode("utf-8"))
        lines.append(b"\r\n")
    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode("utf-8")
    )
    lines.append(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
    lines.append(file_path.read_bytes())
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(lines), boundary


def _post_multipart(
    url: str,
    fields: Dict[str, str],
    file_field: str,
    file_path: Path,
    api_key: str,
    timeout: int = 180,
) -> Dict[str, Any]:
    body, boundary = _encode_multipart(fields, file_field, file_path)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def describe_image(image_path: str | Path, config: AppConfig) -> str:
    if not config.media_ai_enabled or not config.media_vision_model:
        return ""
    path = Path(image_path)
    if not path.exists():
        return ""
    api_key = _api_key(config)
    if not api_key:
        return ""
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    payload = {
        "model": config.media_vision_model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请用中文简短描述这张聊天图片的内容、文字和关键信息，只输出描述，不要客套。",
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
    }
    try:
        data = _post_json(_base_url(config) + "/chat/completions", payload, api_key)
        return str(data["choices"][0]["message"]["content"]).strip()
    except Exception:
        return ""


def transcribe_audio(audio_path: str | Path, config: AppConfig) -> str:
    if not config.media_ai_enabled or not config.media_asr_model:
        return ""
    path = Path(audio_path)
    if not path.exists():
        return ""
    api_key = _api_key(config)
    if not api_key:
        return ""
    try:
        data = _post_multipart(
            _base_url(config) + "/audio/transcriptions",
            {"model": config.media_asr_model},
            "file",
            path,
            api_key,
        )
        if data.get("text"):
            return str(data["text"]).strip()
        if data.get("choices"):
            return str(data["choices"][0].get("text") or data["choices"][0].get("message", {}).get("content") or "").strip()
    except Exception:
        return ""
    return ""


def enrich_media_messages(
    messages: Iterable[Message],
    backend: Any,
    config: AppConfig,
    cache: Optional[Dict[str, str]] = None,
) -> None:
    """尝试识别消息里的图片/语音，并把识别文本追加到消息内容后。"""
    if not config.media_ai_enabled:
        return
    cache = cache if cache is not None else {}
    max_items = max(0, int(config.media_max_items or 10))
    done = 0
    for msg in messages:
        if done >= max_items:
            break
        key = msg.message_id or f"{msg.timestamp}-{msg.content[:20]}"
        if key in cache:
            recognized = cache[key]
        else:
            content = msg.content or ""
            recognized = ""
            try:
                if "[图片]" in content:
                    path = backend.download_media_for_message(msg)
                    if path:
                        recognized = describe_image(path, config)
                elif "[语音]" in content:
                    path = backend.download_media_for_message(msg)
                    if path:
                        recognized = transcribe_audio(path, config)
            except Exception:
                recognized = ""
            cache[key] = recognized
        if recognized and "（识别：" not in (msg.content or ""):
            msg.content = f"{msg.content}\n（识别：{recognized}）"
            done += 1
