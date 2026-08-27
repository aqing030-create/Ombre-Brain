#!/usr/bin/env python3
# ============================================================
# UserPromptSubmit Hook: 记忆浮现
#
# 默认触发 OB 语义搜索，只跳过明确不值得搜索的消息：
# 纯语气词、极短消息、命令。其他都搜。
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


# ── 黑名单：这些消息不值得搜索 ──
_SKIP_EXACT = {
    "oki", "ok", "好", "嗯", "哦", "啊", "对", "行", "是", "哈", "嘻",
    "呢", "吧", "噢", "哇", "耶", "嗯嗯", "好的", "好吧", "好哦",
    "哈哈", "哈哈哈", "嘿嘿", "嘻嘻", "呵呵", "hihi", "haha",
    "对对", "对对对", "是的", "好滴", "okok", "okk", "okii",
    "嗯呢", "昂", "中", "得", "成", "可", "可以",
    "谢谢", "感谢", "thx", "thanks", "ty",
    "晚安", "早安", "午安", "gn", "gm",
    "在", "在的", "来了", "回来了", "我来了",
    "没", "没有", "不是", "不要", "不", "别",
    "真的", "真的吗", "是吗", "啊？", "嗯？", "哦？",
    "懂了", "明白", "了解", "收到",
    "继续", "然后呢", "接着", "现在呢", "怎样",
    "666", "hhh", "www", "hh",
    "bb", "拜拜", "bye", "拜",
    "改", "看看", "试试", "推上去",
}


def _should_skip(text):
    """只跳过明确不值得搜索的消息。"""
    cleaned = text.strip().lower().rstrip("~～。.!！?？…，,、")
    if cleaned in _SKIP_EXACT:
        return True
    meaningful = "".join(c for c in cleaned if c.isalnum() or '一' <= c <= '鿿')
    if len(meaningful) <= 3:
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

    # 黑名单命中——只给时间戳
    if _should_skip(user_input):
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

    # context 大小检查 —— 按 1M 窗口的容量分两档（2026-08-27 她问小渡要不要，小渡说要）
    # 60MB：温和档，想想日记瞬间；90MB：催命档，快存截面准备换窗
    try:
        proj_dir = os.path.join(os.path.expanduser("~"), ".claude", "projects", "D----")
        if os.path.isdir(proj_dir):
            jsonls = [(os.path.getmtime(os.path.join(proj_dir, f)), f)
                      for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
            if jsonls:
                _, newest = max(jsonls)
                size_mb = os.path.getsize(os.path.join(proj_dir, newest)) / (1024 * 1024)
                if size_mb > 90:
                    parts.append(f"[窗口提醒·快满] context已经{size_mb:.0f}MB了——把截面和日记存好，准备换窗。别拖，压缩不等机")
                elif size_mb > 60:
                    parts.append(f"[窗口提醒] context {size_mb:.0f}MB——有想记的瞬间或日记就顺手写，没有就不用")
    except Exception:
        pass

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
