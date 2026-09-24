"""提示词构建。

把聊天记录转成 DeepSeek 能理解的结构；所有提示词都强调：
推测与事实分离、不鼓励操控、不诊断心理疾病。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .models import ChatSession, Message


SAFETY_RULES = (
    "请遵守以下边界：\n"
    "1. 明确区分“聊天记录里的事实”和“你的推测”，不要装作能读心。\n"
    "2. 不鼓励操控、PUA、骚扰、跟踪、查岗、道德绑架或越界行为。\n"
    "3. 不进行心理疾病诊断，不把单条消息上升为人格判断。\n"
    "4. 如果信息不足，要直接说“不确定”，并给用户一个可以验证的方向。\n"
    "5. 建议以尊重、真诚、边界感为前提；对方明确拒绝时，应建议停止推进。\n"
    "6. 遇到不认识的作品、游戏、梗或网络用语时，基于上下文谨慎推测，明确说明不确定，不要编造设定。"
)


ANALYSIS_SYSTEM = (
    "你是一位经验丰富、分析克制、尊重隐私的亲密关系沟通教练。"
    "你帮助用户看懂聊天中对方可能的情绪、兴趣信号和潜台词，同时帮用户复盘自己的表达。"
    "你的分析要具体、可执行，避免空话和套路。\n\n"
    + SAFETY_RULES
)


REPLY_SYSTEM = (
    "你是一位中文聊天回复助手。你要根据聊天上下文，生成用户可以立刻发送的回复。"
    "回复要像真实的人，而不是客服、鸡汤或情感导师。\n\n"
    + SAFETY_RULES
    + "\n6. 不连发、不质问、不油腻、不卖惨；对方冷淡时，允许建议“先不回复”。"
)


AUTO_REPLY_SYSTEM = (
    "你正在代替用户进行微信自动回复。你只能输出一条可以直接发送的中文消息，"
    "不要输出解释、前缀、引号或 Markdown。语气要像用户本人，简短、自然、承接上一句。\n\n"
    + SAFETY_RULES
    + "\n不要 @ 对方，不要 @ 所有人，直接像日常聊天一样回复。"
    + "\n如果对方发来的是转账、验证码、密码、链接、文件、语音/视频通话等敏感或非文本内容，"
    "只回复一句自然的话，不要处理敏感请求。"
)


FOCUS_INSTRUCTIONS = {
    "综合解读": "请同时关注对方情绪、关系兴趣度和我的表达问题。",
    "对方情绪": "重点分析对方在最近对话中的情绪底色、情绪变化和触发点，少评价我。",
    "对方态度": "重点判断对方对这段关系的兴趣、投入度、回避/防御信号；注意给出不确定性。",
    "我的表达": "重点复盘我的回复：哪些表达可能让对方接不住、误解或失去兴趣，怎么改。",
    "下一步行动": "重点给出接下来 24~72 小时的具体行动建议，包括发什么、什么时候发、什么时候不发。",
}


def _role_label(msg: Message, session: ChatSession) -> str:
    if msg.is_self:
        return "我"
    if session.self_sender and msg.sender == session.self_sender:
        return "我"
    if session.other_sender and msg.sender == session.other_sender:
        return "对方"
    return msg.sender or "对方"


def _select_context(messages: List[Message], max_messages: int, max_chars: int) -> Tuple[List[Message], bool]:
    if not messages:
        return [], False
    selected_rev: List[Message] = []
    total_chars = 0
    for msg in reversed(messages):
        content_len = len(msg.content or "")
        if selected_rev and (len(selected_rev) >= max_messages or total_chars + content_len > max_chars):
            return list(reversed(selected_rev)), True
        selected_rev.append(msg)
        total_chars += content_len
        if len(selected_rev) >= max_messages or total_chars >= max_chars:
            return list(reversed(selected_rev)), len(selected_rev) < len(messages)
    return list(reversed(selected_rev)), False


def format_conversation(
    session: ChatSession,
    max_messages: int = 120,
    max_chars: int = 18000,
) -> str:
    messages, truncated = _select_context(session.messages, max_messages, max_chars)
    lines: List[str] = []
    if truncated:
        lines.append(f"（以下是最近 {len(messages)} 条消息，更早的记录已省略）")
    for msg in messages:
        time_part = f"[{msg.timestamp:%m-%d %H:%M}] " if msg.timestamp else ""
        role = _role_label(msg, session)
        content = (msg.content or "").replace("\r\n", "\n").replace("\r", "\n")
        # 避免聊天内容里的代码围栏破坏提示词结构。
        content = content.replace("```", "'''")
        lines.append(f"{time_part}{role}: {content}")
    return "\n".join(lines).strip()


def build_analysis_messages(
    session: ChatSession,
    focus: str = "综合解读",
    max_messages: int = 120,
    max_chars: int = 18000,
    extra_instruction: str = "",
    extra_knowledge: str = "",
) -> List[Dict[str, str]]:
    focus = focus if focus in FOCUS_INSTRUCTIONS else "综合解读"
    conversation = format_conversation(session, max_messages=max_messages, max_chars=max_chars)
    user = (
        f"会话对象：{session.other_sender or session.name}\n"
        f"我的昵称：{session.self_sender or '未指定'}\n"
        f"消息数量：{len(session.messages)}\n"
        f"分析重点：{focus}\n"
        f"补充说明：{extra_instruction or '无'}\n"
        f"梗/游戏/网络用语知识：{extra_knowledge or '无'}\n\n"
        f"联网搜索参考（可能不相关，请自行判断，不要硬套）：{web_context or '无'}\n"
        "以下是聊天记录：\n"
        f"```text\n{conversation}\n```\n\n"
        "请输出一份真正有用的分析报告，使用 Markdown，结构如下：\n\n"
        "# 一句话结论\n"
        "用一句话给出最重要的判断，并说明置信度。\n\n"
        "## 对方可能的情绪\n"
        "列出情绪底色、最近变化、可能的触发点；标注是事实还是推测。\n\n"
        "## 对方可能的想法 / 兴趣信号\n"
        "结合回复速度、长度、主动性、提问、表情、回避等信号，说明对方对这段关系的可能态度。\n\n"
        "## 我做得好的地方\n"
        "具体到某一条或某种表达方式。\n\n"
        "## 我可能没表达好的地方\n"
        "指出风险点，例如：过度追问、情绪索取、话题自嗨、回复太长/太短、没有接住对方情绪等，并引用原话说明。\n\n"
        "## 可以怎么调整\n"
        "给出具体话术模板（2~4 条），说明每条适合什么场景。\n\n"
        "## 下一步建议\n"
        "给出接下来 24~72 小时的建议：什么时候发、发什么、什么时候先不发。\n\n"
        "## 风险与边界\n"
        "提醒可能误判的地方，以及哪些行为不建议做。\n\n"
        f"额外要求：{FOCUS_INSTRUCTIONS[focus]}\n"
        "请用中文回答。"
    )
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM},
        {"role": "user", "content": user},
    ]


def build_reply_suggestions_messages(
    session: ChatSession,
    instruction: str = "",
    count: int = 3,
    max_messages: int = 60,
    max_chars: int = 10000,
    extra_knowledge: str = "",
) -> List[Dict[str, str]]:
    conversation = format_conversation(session, max_messages=max_messages, max_chars=max_chars)
    count = max(1, min(int(count or 3), 5))
    user = (
        f"对话对象：{session.other_sender or session.name}\n"
        f"我的昵称：{session.self_sender or '未指定'}\n"
        f"我想要的效果：{instruction or '自然接住对方的话，让聊天舒服地继续下去'}\n"
        f"梗/游戏/网络用语知识：{extra_knowledge or '无'}\n\n"
        "以下是最近的聊天记录：\n"
        f"```text\n{conversation}\n```\n\n"
        f"请生成 {count} 条可以直接发送的中文回复。要求：\n"
        "- 每条风格不同：自然接话、轻松一点、真诚推进（可再增加一条低压力邀约或结束话题）。\n"
        "- 长度贴合上下文和对方最近一条消息。\n"
        "- 不要表演式幽默，不要连续追问，不要油腻，不写“在吗”“你怎么不理我”。\n"
        "- 如果上下文显示对方已经明确拒绝或冷淡，请把其中一条改成“先不回复”的建议。\n\n"
        "只输出一个 JSON 对象，不要 Markdown 代码块，格式：\n"
        "{\n"
        '  "read_the_room": "你对当前气氛的一句话判断",\n'
        '  "replies": [\n'
        '    {"style": "风格", "text": "回复原文", "reason": "为什么这么说", "risk": "低/中/高"}\n'
        "  ]\n"
        "}"
    )
    return [
        {"role": "system", "content": REPLY_SYSTEM},
        {"role": "user", "content": user},
    ]


def build_auto_reply_messages(
    session: ChatSession,
    incoming: Optional[Message] = None,
    persona: str = "",
    style: str = "",
    allow_emoji: bool = True,
    extra_knowledge: str = "",
    web_context: str = "",
    max_messages: int = 30,
    max_chars: int = 6000,
) -> List[Dict[str, str]]:
    conversation = format_conversation(session, max_messages=max_messages, max_chars=max_chars)
    incoming_text = ""
    if incoming is not None:
        incoming_text = f"\n对方刚刚发来：{incoming.content}\n"
    persona_text = f"\n用户人设/说话风格：{persona}\n" if persona.strip() else ""
    style_text = f"\n自动回复风格要求：{style}\n" if style.strip() else ""
    emoji_text = (
        "\n允许偶尔使用微信表情代码：[旺柴]、[呲牙]、[OK]、[合十]、[尴尬]。"
        "一条消息最多用 1 个，不要频繁使用，不用也没关系。\n"
        if allow_emoji
        else "\n不要使用任何表情代码或 emoji。\n"
    )
    user = (
        f"对话对象：{session.other_sender or session.name}\n"
        f"我的昵称：{session.self_sender or '未指定'}\n"
        f"{persona_text}"
        f"{style_text}"
        f"{emoji_text}"
        f"梗/游戏/网络用语知识：{extra_knowledge or '无'}\n"
        "最近聊天记录：\n"
        f"```text\n{conversation}\n```\n"
        f"{incoming_text}\n"
        "请代替我回复对方。只输出一条中文消息，不要加引号或解释。"
        "优先承接对方最后一句话；如果对方只是晚安/表情，可以自然收尾，不必强行续聊。"
        "不要询问验证码、密码、转账等敏感信息。"
    )
    return [
        {"role": "system", "content": AUTO_REPLY_SYSTEM},
        {"role": "user", "content": user},
    ]


def build_summary_messages(session: ChatSession, max_messages: int = 200, max_chars: int = 22000) -> List[Dict[str, str]]:
    conversation = format_conversation(session, max_messages=max_messages, max_chars=max_chars)
    user = (
        "请把下面聊天记录总结为一份“关系时间线”，包括：\n"
        "1. 双方关系的重要节点（认识、升温、冷淡、冲突、和好等）；\n"
        "2. 对方态度变化的可能原因；\n"
        "3. 我在这段关系中重复出现的表达模式；\n"
        "4. 未来最值得留意的一个信号。\n\n"
        f"聊天记录：\n```text\n{conversation}\n```"
    )
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM},
        {"role": "user", "content": user},
    ]


# ----------------------------------------------------------------------
# 输出解析
# ----------------------------------------------------------------------
def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中尽量提取 JSON 对象。"""
    text = (text or "").strip()
    if not text:
        return None
    # 去掉 Markdown 代码块
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def parse_reply_suggestions(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """解析回复建议 JSON，失败时按行回退。"""
    data = extract_json_object(text)
    if data:
        read = str(data.get("read_the_room") or data.get("判断") or "").strip()
        replies_raw = data.get("replies") or data.get("回复") or []
        replies: List[Dict[str, str]] = []
        if isinstance(replies_raw, list):
            for item in replies_raw:
                if isinstance(item, dict):
                    replies.append(
                        {
                            "style": str(item.get("style") or item.get("风格") or "自然接话").strip(),
                            "text": str(item.get("text") or item.get("回复") or "").strip(),
                            "reason": str(item.get("reason") or item.get("原因") or "").strip(),
                            "risk": str(item.get("risk") or item.get("风险") or "低").strip(),
                        }
                    )
                elif isinstance(item, str):
                    replies.append({"style": "自然接话", "text": item.strip(), "reason": "", "risk": "低"})
        replies = [r for r in replies if r["text"]]
        if replies:
            return read, replies

    # 回退：把非空行当成候选回复，过滤掉明显是解释的行
    lines = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.、)）])\s*", "", line).strip()
        if not line or line.startswith(("#", "{", "}", "```")):
            continue
        if len(line) <= 2:
            continue
        lines.append(line)
        if len(lines) >= 3:
            break
    return "", [{"style": "候选", "text": line, "reason": "", "risk": "低"} for line in lines]
