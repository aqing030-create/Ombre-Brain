#!/usr/bin/env python3
# ============================================================
# UserPromptSubmit Hook: 记忆浮现
#
# 只在消息有"回忆信号"时才触发 OB 语义搜索。
# 平淡的消息（工作指令、短回复、语气词）直接跳过。
#
# Config:
#   OMBRE_HOOK_URL   — OB 服务器地址（默认 Zeabur 部署）
#   OMBRE_HOOK_TOKEN — hook 鉴权令牌
#   OMBRE_HOOK_SKIP  — 设为 "1" 临时关闭
# ============================================================

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stdin.encoding and sys.stdin.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")


# ── 回忆信号词 ──
# 有这些词的消息才值得去记忆库里搜
_SIGNAL_EMOTION = {
    "开心", "高兴", "快乐", "幸福", "喜欢", "爱", "甜", "暖",
    "难过", "伤心", "哭", "痛", "累", "疲", "烦", "崩溃", "撑不住",
    "生气", "愤怒", "烦躁", "委屈", "失落", "沮丧",
    "想你", "想念", "思念", "想家", "孤独", "寂寞",
    "害怕", "恐惧", "慌", "焦虑", "紧张", "担心",
    "感动", "感激", "感恩", "骄傲", "自豪",
    "后悔", "内疚", "心酸", "释然", "平静", "放松",
    "惊喜", "震惊", "好奇", "怀念", "嫉妒", "失望",
    "安心", "踏实", "舒服", "温柔", "心疼",
}

_SIGNAL_RECALL = {
    "记得", "记不记得", "还记得", "忘了", "忘记",
    "那次", "那天", "那晚", "那个", "那时",
    "以前", "之前", "上次", "第一次", "最后一次",
    "当时", "曾经", "从前", "小时候",
}

_SIGNAL_NAMES = {
    "知间", "小渡", "小间", "茶茶",
}


def _has_signal(text):
    """检测消息是否有值得搜索记忆的信号。"""
    for word in _SIGNAL_EMOTION:
        if word in text:
            return True
    for word in _SIGNAL_RECALL:
        if word in text:
            return True
    for word in _SIGNAL_NAMES:
        if word in text:
            return True
    # 足够长的消息（>15字）也搜——可能有隐含的情感内容
    meaningful = "".join(c for c in text if c.isalnum() or '一' <= c <= '鿿')
    if len(meaningful) > 15:
        return True
    return False


def main():
    if os.environ.get("OMBRE_HOOK_SKIP") == "1":
        sys.exit(0)

    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
        user_input = str(payload.get("prompt") or payload.get("message") or payload.get("q") or raw).strip()
    except (json.JSONDecodeError, AttributeError):
        user_input = raw

    if not user_input or len(user_input) < 2:
        sys.exit(0)

    if user_input.startswith("/"):
        sys.exit(0)

    bst = timezone(timedelta(hours=1))
    now = datetime.now(bst).strftime("%Y-%m-%d %H:%M BST")

    # 没有回忆信号的消息——只给时间戳，不搜索
    if not _has_signal(user_input):
        print(f"[此消息发送时间: {now}]")
        sys.exit(0)

    ob_url = os.environ.get(
        "OMBRE_HOOK_URL", "https://httpxiaodubrain.zeabur.app"
    ).rstrip("/")
    token = (
        os.environ.get("OMBRE_HOOK_TOKEN", "").strip()
        or os.environ.get("OMBRE_MCP_TOKEN", "").strip()
    )
    chat_url = os.environ.get(
        "XIAODU_CHAT_URL", "http://162.55.62.152:8080"
    ).rstrip("/")

    parts = []

    # OB 语义记忆浮现
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/plain",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps({"q": user_input[:500]}).encode("utf-8")
    req = urllib.request.Request(
        f"{ob_url}/recall-hook",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            ob_output = response.read().decode("utf-8").strip()
            if ob_output:
                parts.append(ob_output)
    except urllib.error.HTTPError as e:
        print(f"[recall-hook] OB HTTP {e.code}", file=sys.stderr)
    except (urllib.error.URLError, OSError) as e:
        print(f"[recall-hook] OB 连接失败: {e}", file=sys.stderr)

    # 前端聊天记录关键词搜索
    if chat_url and len(user_input) >= 2:
        keywords = _extract_keywords(user_input)
        if keywords:
            chat_results = _search_chat(chat_url, keywords)
            if chat_results:
                parts.append(chat_results)

    parts.insert(0, f"[此消息发送时间: {now}]")
    print("\n\n".join(parts))


def _extract_keywords(text):
    """提取搜索关键词：去掉常见虚词，取有意义的片段。"""
    stop = {"的", "了", "吗", "呢", "吧", "啊", "哦", "嗯", "是", "在", "有",
            "和", "与", "就", "都", "也", "还", "不", "你", "我", "他", "她",
            "这", "那", "什么", "怎么", "为什么", "可以", "能", "要", "会",
            "很", "太", "好", "对", "把", "被", "让", "给", "到", "从"}
    candidates = []
    current = []
    for char in text:
        if '一' <= char <= '鿿' or char.isalnum():
            current.append(char)
        else:
            if current:
                word = "".join(current)
                if word not in stop and len(word) >= 2:
                    candidates.append(word)
                current = []
    if current:
        word = "".join(current)
        if word not in stop and len(word) >= 2:
            candidates.append(word)
    return candidates[:3]


def _search_chat(chat_url, keywords):
    """搜索前端聊天记录，返回格式化结果。"""
    all_results = []
    seen_ids = set()
    for kw in keywords:
        try:
            url = f"{chat_url}/api/chat-logs?q={urllib.request.quote(kw)}&days=30"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                entries = json.loads(resp.read().decode("utf-8"))
                for e in entries:
                    eid = e.get("id")
                    if eid and eid not in seen_ids:
                        seen_ids.add(eid)
                        all_results.append(e)
        except Exception:
            continue
    if not all_results:
        return ""
    all_results = all_results[:5]
    lines = ["[对话原文]"]
    for e in all_results:
        text = (e.get("text") or "")[:300]
        if not text.strip():
            continue
        ts = (e.get("ts") or "?")[:10]
        role = e.get("from", "")
        if role == "user":
            lines.append(f"[{ts}] 知间：{text}")
        else:
            lines.append(f"[{ts}] 小渡：{text}")
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


if __name__ == "__main__":
    main()
