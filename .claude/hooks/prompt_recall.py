#!/usr/bin/env python3
# ============================================================
# UserPromptSubmit Hook: 记忆浮现
#
# 每次用户发消息时自动调用 OB 的 /recall-hook，
# 返回语义相关的记忆片段注入 CC 上下文。
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

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stdin.encoding and sys.stdin.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")


def main():
    if os.environ.get("OMBRE_HOOK_SKIP") == "1":
        sys.exit(0)

    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    # CC may pass JSON or plain text on stdin
    try:
        payload = json.loads(raw)
        user_input = str(payload.get("prompt") or payload.get("message") or payload.get("q") or raw).strip()
    except (json.JSONDecodeError, AttributeError):
        user_input = raw

    if not user_input or len(user_input) < 2:
        sys.exit(0)

    # 跳过纯命令（/开头）
    if user_input.startswith("/"):
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

    # 1) OB 语义记忆浮现
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
        with urllib.request.urlopen(req, timeout=10) as response:
            ob_output = response.read().decode("utf-8").strip()
            if ob_output:
                parts.append(ob_output)
    except urllib.error.HTTPError as e:
        print(f"[recall-hook] OB HTTP {e.code}", file=sys.stderr)
    except (urllib.error.URLError, OSError) as e:
        print(f"[recall-hook] OB 连接失败: {e}", file=sys.stderr)

    # 2) 前端聊天记录关键词搜索
    if chat_url and len(user_input) >= 2:
        keywords = _extract_keywords(user_input)
        if keywords:
            chat_results = _search_chat(chat_url, keywords)
            if chat_results:
                parts.append(chat_results)

    if parts:
        print("\n\n".join(parts))


def _extract_keywords(text):
    """提取搜索关键词：去掉常见虚词，取有意义的片段。"""
    stop = {"的", "了", "吗", "呢", "吧", "啊", "哦", "嗯", "是", "在", "有",
            "和", "与", "就", "都", "也", "还", "不", "你", "我", "他", "她",
            "这", "那", "什么", "怎么", "为什么", "可以", "能", "要", "会",
            "很", "太", "好", "对", "把", "被", "让", "给", "到", "从"}
    words = []
    for char in text:
        if '一' <= char <= '鿿' or char.isalnum():
            words.append(char)
    # 取2-4字的连续片段作为关键词
    candidates = []
    i = 0
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
    # 最多返回3条，控制token
    all_results = all_results[:3]
    lines = ["[对话原文]"]
    for e in all_results:
        user_text = (e.get("user") or "")[:200]
        ai_text = (e.get("ai") or "")[:300]
        lines.append(f"[{e.get('date', '?')}] 知间：{user_text}")
        lines.append(f"  小渡：{ai_text}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
