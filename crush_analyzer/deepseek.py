"""DeepSeek（OpenAI 兼容）客户端。

默认调用 ``https://api.deepseek.com/chat/completions``，也支持任意 OpenAI 兼容
接口，例如本地 Ollama、OneAPI、Moonshot 等，只需在设置里修改 Base URL。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import socket
import ssl
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

from .config import AppConfig
from .models import ChatSession, Message
from .version import __version__ as CRUSH_VERSION
from .prompts import (
    build_analysis_messages,
    build_auto_reply_messages,
    build_reply_suggestions_messages,
    build_summary_messages,
    parse_reply_suggestions,
)


WECHAT_EMOJI_CODES = ("[旺柴]", "[呲牙]", "[OK]", "[合十]", "[尴尬]")


class DeepSeekError(RuntimeError):
    """调用大模型接口失败。"""

    def __init__(self, message: str, status_code: Optional[int] = None, response_text: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

    @property
    def user_message(self) -> str:
        if self.status_code == 401:
            return "API Key 无效或未授权，请检查设置。"
        if self.status_code == 402:
            return "DeepSeek 账户余额不足。"
        if self.status_code == 429:
            return "请求太频繁或触发限流，请稍后再试。"
        if self.status_code and self.status_code >= 500:
            return "模型服务暂时不可用，请稍后重试。"
        return str(self)


class HttpTransportError(RuntimeError):
    """网络层错误，不依赖第三方库。"""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class HttpResponse:
    status_code: int
    text: str

    def json(self) -> Any:
        return json.loads(self.text or "{}")


@dataclass
class ChatResponse:
    content: str
    model: str = ""
    usage: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = {}


CURRENCY_SYMBOLS = {"CNY": "¥", "RMB": "¥", "USD": "$", "EUR": "€"}


@dataclass
class UsageInfo:
    """一次调用的 token 和费用估算。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    cost: float = 0.0
    currency: str = "CNY"
    model: str = ""

    @property
    def symbol(self) -> str:
        return CURRENCY_SYMBOLS.get((self.currency or "CNY").upper(), self.currency or "¥")

    @property
    def input_tokens(self) -> int:
        return self.cache_hit_tokens + self.cache_miss_tokens

    def format_short(self) -> str:
        return f"{self.total_tokens:,} tokens · {self.symbol}{self.cost:.4f}"

    def format_detail(self) -> str:
        return (
            f"输入 {self.input_tokens:,}（缓存命中 {self.cache_hit_tokens:,} / 未命中 {self.cache_miss_tokens:,}）"
            f" · 输出 {self.completion_tokens:,} · 合计 {self.total_tokens:,} tokens · "
            f"估算费用 {self.symbol}{self.cost:.4f} {self.currency}"
        )


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def parse_usage(usage: Optional[Dict[str, Any]], config: AppConfig, model: str = "") -> UsageInfo:
    """把 API 返回的 usage 转成 token + 费用估算。

    DeepSeek 返回 ``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens``；
    部分 OpenAI 兼容接口返回 ``prompt_tokens_details.cached_tokens``。
    """
    usage = usage or {}
    prompt = _as_int(usage.get("prompt_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    total = _as_int(usage.get("total_tokens")) or (prompt + completion)

    details = usage.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}
    hit = _as_int(usage.get("prompt_cache_hit_tokens"))
    if not hit:
        hit = _as_int(details.get("cached_tokens"))
    miss = _as_int(usage.get("prompt_cache_miss_tokens"))
    if not hit and not miss:
        # 没有缓存字段时，全部按未命中输入价格估算。
        miss = prompt
    elif not miss:
        miss = max(prompt - hit, 0)

    unit = max(_as_int(config.price_unit) or 1_000_000, 1)
    cost = (
        hit / unit * float(config.price_input_cache_hit or 0)
        + miss / unit * float(config.price_input_cache_miss or 0)
        + completion / unit * float(config.price_output or 0)
    )
    return UsageInfo(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        cost=cost,
        currency=config.price_currency or "CNY",
        model=model,
    )


class DeepSeekClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.last_usage: Dict[str, Any] = {}
        self.last_usage_info = UsageInfo()
        self.last_model = ""

    # ------------------------------------------------------------------
    # 基础调用
    # ------------------------------------------------------------------
    @property
    def api_key(self) -> str:
        return (self.config.api_key or "").strip()

    @property
    def base_url(self) -> str:
        return (self.config.base_url or "https://api.deepseek.com").strip().rstrip("/")

    def endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return base + "/chat/completions"
        # DeepSeek 官方地址端点没有 /v1；OpenAI 兼容地址若带 /v1 已在上面处理。
        return base + "/chat/completions"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"CrushChatAnalyzer/{CRUSH_VERSION}",
        }
        return headers

    def _post_json(self, url: str, payload: Dict[str, Any], timeout: int) -> HttpResponse:
        """使用 Python 标准库发送 HTTPS POST，避免依赖 requests。"""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(),
            method="POST",
        )
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:
                status = int(getattr(resp, "status", 0) or resp.getcode() or 0)
                body = resp.read().decode("utf-8", errors="replace")
                return HttpResponse(status_code=status, text=body)
        except urllib.error.HTTPError as exc:
            # 4xx/5xx 也让上层统一按状态码处理，方便显示具体错误。
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            return HttpResponse(status_code=int(exc.code or 0), text=body)
        except (socket.timeout, TimeoutError) as exc:
            raise HttpTransportError("请求超时", retryable=True) from exc
        except ssl.SSLError as exc:
            raise HttpTransportError(f"HTTPS 证书或网络错误：{exc}", retryable=False) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            retryable = not isinstance(reason, ssl.SSLError)
            raise HttpTransportError(f"网络连接失败：{reason}", retryable=retryable) from exc
        except OSError as exc:
            raise HttpTransportError(f"网络请求失败：{exc}", retryable=True) from exc

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        retries: int = 2,
    ) -> str:
        return self.chat_response(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            retries=retries,
        ).content

    def chat_response(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        retries: int = 2,
    ) -> ChatResponse:
        if not self.api_key:
            raise DeepSeekError("还没有配置 DeepSeek API Key。")
        if not messages:
            raise DeepSeekError("消息列表不能为空。")

        payload: Dict[str, Any] = {
            "model": model or self.config.model or "deepseek-chat",
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else float(temperature),
            "max_tokens": int(self.config.max_tokens if max_tokens is None else max_tokens),
            "stream": False,
        }
        url = self.endpoint()
        last_error: Optional[Exception] = None
        timeout = max(5, int(self.config.timeout or 90))
        for attempt in range(max(1, retries + 1)):
            try:
                resp = self._post_json(url, payload, timeout)
            except HttpTransportError as exc:
                last_error = exc
                if attempt < retries and exc.retryable:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise DeepSeekError(str(exc)) from exc

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                detail = _extract_error_detail(resp)
                raise DeepSeekError(
                    detail or f"接口返回 HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    response_text=resp.text,
                )
            try:
                data = resp.json()
            except ValueError as exc:
                raise DeepSeekError("接口返回的不是合法 JSON。", response_text=resp.text[:500]) from exc
            try:
                choice = data["choices"][0]
                content = choice.get("message", {}).get("content") or choice.get("text") or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise DeepSeekError("接口返回格式异常，未找到回复内容。", response_text=resp.text[:500]) from exc
            content = (content or "").strip()
            if not content:
                raise DeepSeekError("模型返回了空内容，请换一种问法或稍后重试。")
            usage = data.get("usage") or {}
            model_name = str(data.get("model") or payload["model"])
            self.last_usage = usage
            self.last_model = model_name
            self.last_usage_info = parse_usage(usage, self.config, model=model_name)
            return ChatResponse(content=content, model=model_name, usage=usage)
        raise DeepSeekError(f"请求失败：{last_error}")

    def test_connection(self) -> str:
        """发送一条极短消息测试连通性。"""
        return self.chat(
            [
                {"role": "system", "content": "你是一个测试助手，只回复“连接成功”。"},
                {"role": "user", "content": "请回复：连接成功"},
            ],
            temperature=0,
            max_tokens=16,
            retries=0,
        )

    # ------------------------------------------------------------------
    # 业务封装
    # ------------------------------------------------------------------
    def analyze(
        self,
        session: ChatSession,
        focus: str = "综合解读",
        extra_instruction: str = "",
    ) -> str:
        messages = build_analysis_messages(
            session,
            focus=focus,
            max_messages=self.config.max_context_messages,
            max_chars=self.config.max_context_chars,
            extra_instruction=extra_instruction,
            extra_knowledge=self.config.custom_knowledge,
        )
        return self.chat(messages, temperature=0.5, max_tokens=max(2500, int(self.config.max_tokens or 0)))

    def suggest_replies(
        self,
        session: ChatSession,
        instruction: str = "",
        count: int = 3,
    ):
        messages = build_reply_suggestions_messages(
            session,
            instruction=instruction,
            count=count,
            max_messages=min(self.config.max_context_messages, 80),
            max_chars=min(self.config.max_context_chars, 12000),
            extra_knowledge=self.config.custom_knowledge,
        )
        raw = self.chat(messages, temperature=0.85)
        return parse_reply_suggestions(raw)

    def auto_reply(
        self,
        session: ChatSession,
        incoming: Optional[Message] = None,
        persona: str = "",
        style: str = "",
    ) -> str:
        messages = build_auto_reply_messages(
            session,
            incoming=incoming,
            persona=persona or self.config.system_persona,
            style=style or self.config.auto_reply_style,
            allow_emoji=bool(self.config.auto_reply_allow_emoji),
            extra_knowledge=self.config.custom_knowledge,
            max_messages=min(self.config.max_context_messages, 40),
            max_chars=min(self.config.max_context_chars, 8000),
        )
        text = self.chat(messages, temperature=0.8, max_tokens=220)
        return _clean_single_reply(text)

    def summarize(self, session: ChatSession) -> str:
        messages = build_summary_messages(
            session,
            max_messages=max(self.config.max_context_messages, 200),
            max_chars=max(self.config.max_context_chars, 22000),
        )
        return self.chat(messages, temperature=0.4)


def _extract_error_detail(resp: Any) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)
            if err:
                return str(err)
            if data.get("message"):
                return str(data["message"])
    except (ValueError, json.JSONDecodeError):
        pass
    text = (resp.text or "").strip()
    return text[:300]


def _clean_single_reply(text: str) -> str:
    """去掉模型可能加上的引号、前缀和 Markdown。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if lines:
            text = lines[-1].strip()
    # 去掉“回复：”“可以这样回：”等前缀
    for prefix in ("回复：", "回复:", "可以回：", "可以回:", "建议回复：", "建议回复:", "你回：", "你回:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    # 去掉开头的 @昵称 / @所有人，自动回复不需要每次 @ 对方。
    text = re.sub(r"^(?:@[^\s，。,\.!！?？:：]+[\s,，]*)+", "", text).strip()
    # 去掉 Unicode emoji，只保留微信表情代码白名单。
    text = re.sub(
        r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF\u2600-\u26FF]",
        "",
        text,
    )
    seen_codes: list[str] = []

    def _bracket_emoji(match: "re.Match[str]") -> str:
        code = match.group(0)
        if code in WECHAT_EMOJI_CODES:
            if seen_codes:
                return ""
            seen_codes.append(code)
            return code
        return code

    text = re.sub(r"\[[^\[\]]{1,8}\]", _bracket_emoji, text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # 去掉包裹的成对引号
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return text
