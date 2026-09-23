"""本地聊天速览。

这个模块不调用任何大模型，负责在无法联网/未配置 API Key 时也给出一些
可解释的统计信号。正式分析仍推荐使用 DeepSeek。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

from .models import ChatSession, Message


QUESTION_MARKS = "?？"
EMOJI_RE = re.compile(
    "[" 
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)
WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{2,}")

POSITIVE_WORDS = (
    "哈哈",
    "嘿嘿",
    "嘻嘻",
    "开心",
    "高兴",
    "喜欢",
    "想你",
    "可爱",
    "有趣",
    "好玩",
    "好呀",
    "可以",
    "当然",
    "期待",
    "晚安",
    "早安",
    "么么",
    "比心",
    "爱你",
    "棒",
    "赞",
    "不错",
    "温柔",
)
NEGATIVE_WORDS = (
    "烦",
    "累",
    "难过",
    "不开心",
    "讨厌",
    "无语",
    "算了",
    "随便",
    "哦",
    "嗯",
    "困",
    "忙",
    "没空",
    "不想",
    "再说",
    "不知道",
    "也许",
    "可能",
    "抱歉",
    "对不起",
)
COLD_WORDS = ("哦", "嗯", "好吧", "随便", "再说", "不知道", "睡了", "忙", "在忙")
INTEREST_WORDS = (
    "在干嘛",
    "在吗",
    "吃了吗",
    "想你",
    "晚安",
    "早安",
    "约",
    "见面",
    "周末",
    "有空",
    "照片",
    "分享",
    "哈哈",
)
HESITATION_WORDS = ("可能", "也许", "再说", "看看", "到时候", "不确定", "应该")


@dataclass
class TextStats:
    count: int = 0
    chars: int = 0
    questions: int = 0
    emojis: int = 0
    exclamations: int = 0
    positive: int = 0
    negative: int = 0
    cold: int = 0
    interest: int = 0
    hesitation: int = 0
    night: int = 0
    short_replies: int = 0

    @property
    def avg_chars(self) -> float:
        return self.chars / self.count if self.count else 0.0


@dataclass
class ConversationStats:
    total: int = 0
    self_count: int = 0
    other_count: int = 0
    unknown_count: int = 0
    date_range: str = ""
    duration_days: float = 0.0
    self_started: int = 0
    other_started: int = 0
    self_stats: TextStats = field(default_factory=TextStats)
    other_stats: TextStats = field(default_factory=TextStats)
    reply_self_minutes: List[float] = field(default_factory=list)
    reply_other_minutes: List[float] = field(default_factory=list)
    hourly_counts: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    daily_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def self_ratio(self) -> float:
        return self.self_count / self.total if self.total else 0.0

    @property
    def median_reply_self(self) -> Optional[float]:
        return median(self.reply_self_minutes) if self.reply_self_minutes else None

    @property
    def median_reply_other(self) -> Optional[float]:
        return median(self.reply_other_minutes) if self.reply_other_minutes else None


def _contains_any(text: str, words: Iterable[str]) -> int:
    return sum(1 for w in words if w in text)


def _count_stats(messages: List[Message]) -> TextStats:
    stats = TextStats()
    for msg in messages:
        text = msg.content or ""
        stats.count += 1
        stats.chars += len(text)
        stats.questions += sum(text.count(ch) for ch in QUESTION_MARKS)
        stats.exclamations += sum(text.count(ch) for ch in "!！")
        stats.emojis += len(EMOJI_RE.findall(text))
        stats.positive += _contains_any(text, POSITIVE_WORDS)
        stats.negative += _contains_any(text, NEGATIVE_WORDS)
        stats.cold += _contains_any(text, COLD_WORDS)
        stats.interest += _contains_any(text, INTEREST_WORDS)
        stats.hesitation += _contains_any(text, HESITATION_WORDS)
        if msg.timestamp and (msg.timestamp.hour >= 23 or msg.timestamp.hour < 6):
            stats.night += 1
        if len(text.strip()) <= 2:
            stats.short_replies += 1
    return stats


def _split_sessions(messages: List[Message], gap_minutes: int = 360) -> List[List[Message]]:
    """按时间间隔把消息切成若干“对话回合”，用于统计谁先开口。"""
    if not messages:
        return []
    sessions: List[List[Message]] = [[messages[0]]]
    for prev, cur in zip(messages, messages[1:]):
        if prev.timestamp and cur.timestamp:
            gap = (cur.timestamp - prev.timestamp).total_seconds() / 60
            if gap > gap_minutes:
                sessions.append([cur])
                continue
        sessions[-1].append(cur)
    return sessions


def compute_stats(messages: List[Message]) -> ConversationStats:
    stats = ConversationStats()
    stats.total = len(messages)
    if not messages:
        return stats

    stats.self_count = sum(1 for m in messages if m.is_self)
    stats.other_count = sum(1 for m in messages if not m.is_self)
    stats.unknown_count = sum(1 for m in messages if not m.sender)
    stats.self_stats = _count_stats([m for m in messages if m.is_self])
    stats.other_stats = _count_stats([m for m in messages if not m.is_self])

    timestamps = [m.timestamp for m in messages if m.timestamp]
    if timestamps:
        first, last = min(timestamps), max(timestamps)
        stats.date_range = f"{first:%Y-%m-%d %H:%M} ~ {last:%Y-%m-%d %H:%M}"
        stats.duration_days = max((last - first).total_seconds() / 86400, 0.0)
        for m in messages:
            if m.timestamp:
                stats.hourly_counts[m.timestamp.hour] += 1
                stats.daily_counts[m.timestamp.strftime("%Y-%m-%d")] += 1

    for turn in _split_sessions(messages):
        if not turn:
            continue
        first_is_self = turn[0].is_self
        if first_is_self:
            stats.self_started += 1
        else:
            stats.other_started += 1

    # 回复间隔：只有对方/我交替时才统计
    for prev, cur in zip(messages, messages[1:]):
        if prev.is_self == cur.is_self:
            continue
        if not prev.timestamp or not cur.timestamp:
            continue
        gap = max((cur.timestamp - prev.timestamp).total_seconds() / 60, 0)
        if cur.is_self:
            stats.reply_self_minutes.append(gap)
        else:
            stats.reply_other_minutes.append(gap)

    return stats


def _fmt_minutes(minutes: Optional[float]) -> str:
    if minutes is None:
        return "暂无数据"
    if minutes < 1:
        return "1 分钟内"
    if minutes < 60:
        return f"{minutes:.0f} 分钟"
    if minutes < 60 * 24:
        return f"{minutes / 60:.1f} 小时"
    return f"{minutes / 60 / 24:.1f} 天"


def _emotion_label(stats: TextStats) -> str:
    score = stats.positive - stats.negative - stats.cold
    if stats.count == 0:
        return "暂无数据"
    if score >= 2 or stats.positive > stats.negative + stats.cold:
        return "偏积极、愿意互动"
    if stats.negative + stats.cold > stats.positive + 1:
        return "偏疲惫或低回应"
    return "整体平稳，情绪信号不明显"


def _interest_label(stats: ConversationStats) -> Tuple[str, str]:
    other = stats.other_stats
    if other.count == 0:
        return "未知", "对方消息太少。"
    reasons: List[str] = []
    score = 0
    if other.questions >= max(2, other.count // 5):
        score += 2
        reasons.append("对方提问较多，愿意把话题接下去")
    if other.avg_chars >= max(12, stats.self_stats.avg_chars * 0.9):
        score += 1
        reasons.append("对方回复长度不敷衍")
    if other.interest >= 1:
        score += 1
        reasons.append("出现主动关心/分享/约见类表达")
    if stats.median_reply_other is not None and stats.median_reply_other <= 30:
        score += 1
        reasons.append("对方回复速度较快")
    if other.positive > other.negative + other.cold:
        score += 1
        reasons.append("正向语气词/表情较多")
    if other.cold >= max(2, other.count // 6) or (stats.median_reply_other or 0) >= 360:
        score -= 2
        reasons.append("冷回复或长时间不回较明显")
    if other.hesitation >= max(1, other.count // 8):
        score -= 1
        reasons.append("出现较多犹豫/回避词")
    if score >= 4:
        return "较高", "；".join(reasons[:3])
    if score >= 2:
        return "中等", "；".join(reasons[:3]) or "有一点兴趣信号，但还需要更多互动验证。"
    if score <= -1:
        return "偏低", "；".join(reasons[:3])
    return "一般", "；".join(reasons[:3]) or "暂时看不出明显倾向。"


def local_analysis(session: ChatSession) -> str:
    """生成不依赖大模型的本地速览报告。"""
    messages = session.messages
    stats = compute_stats(messages)
    if not messages:
        return "当前会话没有消息。"

    interest_level, interest_reason = _interest_label(stats)
    self_e = _emotion_label(stats.self_stats)
    other_e = _emotion_label(stats.other_stats)

    lines: List[str] = []
    lines.append("## 本地速览（未调用 AI）")
    if stats.date_range:
        lines.append(f"- 时间范围：{stats.date_range}，约 {stats.duration_days:.1f} 天")
    lines.append(f"- 消息总数：{stats.total} 条（我 {stats.self_count} / 对方 {stats.other_count}）")
    lines.append(f"- 平均消息长度：我 {stats.self_stats.avg_chars:.1f} 字 / 对方 {stats.other_stats.avg_chars:.1f} 字")
    lines.append(f"- 谁先开启对话：我 {stats.self_started} 次 / 对方 {stats.other_started} 次")
    lines.append(
        f"- 回复间隔中位数：我回复对方 {_fmt_minutes(stats.median_reply_self)} / 对方回复我 {_fmt_minutes(stats.median_reply_other)}"
    )
    lines.append(
        f"- 问号数量：我 {stats.self_stats.questions} / 对方 {stats.other_stats.questions}；表情：我 {stats.self_stats.emojis} / 对方 {stats.other_stats.emojis}"
    )
    lines.append(f"- 对方情绪粗略信号：{other_e}")
    lines.append(f"- 我的语气粗略信号：{self_e}")
    lines.append("")
    lines.append("## 关系信号（启发式，仅供参考）")
    lines.append(f"- 对方兴趣/投入度：**{interest_level}**。{interest_reason}")
    if stats.self_ratio > 0.62:
        lines.append("- 你发消息的占比偏高，可能存在“你追对方退”的风险，建议留一点空间给对方主动。")
    elif stats.self_ratio < 0.38 and stats.other_count > 3:
        lines.append("- 对方主动消息较多，整体节奏对你有一定兴趣；你可以适当主动收尾或提出下一次互动。")
    else:
        lines.append("- 双方消息量比较接近，节奏相对平衡。")

    # 最近三条给 3 个可行建议
    lines.append("")
    lines.append("## 可调整方向")
    suggestions: List[str] = []
    if stats.other_stats.short_replies >= max(2, stats.other_stats.count // 4):
        suggestions.append("对方短回复偏多，先降低连续追问频率，换成“分享+轻提问”的方式。")
    if stats.self_stats.negative > stats.self_stats.positive:
        suggestions.append("你的消息里负面词偏多，可以尝试把抱怨改写成具体感受 + 期待。")
    if stats.self_stats.questions > max(3, stats.other_stats.questions * 2):
        suggestions.append("你的提问远多于对方，容易变成采访式聊天；多用陈述句抛出可接的话题。")
    suggestions.append("把最有回应的一条话题延伸下去，不要频繁换新话题。")
    suggestions.append("对方明确拒绝或冷淡时，先暂停输出，给彼此留出空间。")
    for idx, suggestion in enumerate(list(dict.fromkeys(suggestions))[:4], start=1):
        lines.append(f"{idx}. {suggestion}")
    lines.append("")
    lines.append("> 本地分析只能识别部分关键词，结论可能不准。配置 DeepSeek API Key 后可以获得更细的语义分析。")
    return "\n".join(lines)
