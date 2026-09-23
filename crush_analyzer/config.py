"""应用配置。

优先读取环境变量，其次读取用户配置文件；配置文件不会保存到项目目录中，
避免 API Key 被误提交。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def app_home() -> Path:
    """返回配置目录。可用 CRUSH_ANALYZER_HOME 覆盖，方便测试。"""
    override = os.environ.get("CRUSH_ANALYZER_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "CrushChatAnalyzer"
    return Path.home() / ".config" / "crush_chat_analyzer"


@dataclass
class AppConfig:
    # DeepSeek / OpenAI 兼容接口
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.7
    max_tokens: int = 3000
    timeout: int = 90

    # Token 费用估算（单位：price_currency / 1M tokens）
    # 默认按 DeepSeek 官方 deepseek-chat 常见价格填写，实际以账单为准。
    price_input_cache_hit: float = 0.5
    price_input_cache_miss: float = 2.0
    price_output: float = 8.0
    price_currency: str = "CNY"
    price_unit: int = 1_000_000

    # 分析行为
    max_context_messages: int = 120
    max_context_chars: int = 18000
    system_persona: str = ""
    custom_knowledge: str = ""
    analysis_focus: str = "综合解读"

    # 微信接入
    wechat_self_name: str = ""  # 我在微信里的昵称，用于识别自己发的消息
    max_import_messages: int = 5000  # 从微信数据库读取的最大消息数

    # 图片 / 语音内容识别（可选，OpenAI 兼容接口）
    media_ai_enabled: bool = False
    media_ai_base_url: str = ""
    media_ai_api_key: str = ""
    media_vision_model: str = ""
    media_asr_model: str = "whisper-1"
    media_max_items: int = 10

    # 自动回复
    auto_reply_enabled: bool = False
    auto_reply_contact: str = ""
    auto_reply_poll_interval: int = 5
    auto_reply_quiet_seconds: int = 6
    auto_reply_dry_run: bool = True
    auto_reply_max_per_minute: int = 6
    auto_reply_skip_keywords: str = "转账,收款,语音通话,视频通话,文件,链接,验证码"
    auto_reply_greeting: str = ""
    auto_reply_style: str = "自然、简短、像本人"
    auto_reply_allow_emoji: bool = True

    # 程序更新
    auto_update_enabled: bool = True
    last_update_check: str = ""

    # 界面
    theme: str = "light"
    font_family: str = "Microsoft YaHei UI"

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        cfg = cls()
        file_path = Path(path) if path else app_home() / "config.json"
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                cfg.update(data)
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        # 环境变量优先级最高；方便 CI/临时使用
        env_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if env_key:
            cfg.api_key = env_key
        if os.environ.get("DEEPSEEK_BASE_URL"):
            cfg.base_url = os.environ["DEEPSEEK_BASE_URL"]
        if os.environ.get("DEEPSEEK_MODEL"):
            cfg.model = os.environ["DEEPSEEK_MODEL"]
        return cfg

    def update(self, data: Dict[str, Any]) -> None:
        allowed = {f.name for f in fields(self)}
        for key, value in (data or {}).items():
            if key in allowed:
                setattr(self, key, value)

    def save(self, path: Optional[Path] = None) -> Path:
        file_path = Path(path) if path else app_home() / "config.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        # API Key 仍然写入本地用户目录，方便下次打开；界面上提供清除按钮。
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return file_path

    def masked_api_key(self) -> str:
        key = self.api_key or ""
        if len(key) <= 8:
            return "*" * len(key)
        return key[:4] + "*" * (len(key) - 8) + key[-4:]


def config_path() -> Path:
    return app_home() / "config.json"
