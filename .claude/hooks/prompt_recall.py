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


def main():
    if os.environ.get("OMBRE_HOOK_SKIP") == "1":
        sys.exit(0)

    user_input = sys.stdin.read().strip()
    if not user_input or len(user_input) < 2:
        sys.exit(0)

    # 跳过纯命令（/开头）
    if user_input.startswith("/"):
        sys.exit(0)

    base_url = os.environ.get(
        "OMBRE_HOOK_URL", "https://httpxiaodubrain.zeabur.app"
    ).rstrip("/")
    token = (
        os.environ.get("OMBRE_HOOK_TOKEN", "").strip()
        or os.environ.get("OMBRE_MCP_TOKEN", "").strip()
    )

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/plain",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps({"q": user_input[:500]}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/recall-hook",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            output = response.read().decode("utf-8").strip()
            if output:
                print(output)
    except urllib.error.HTTPError as e:
        print(
            f"[recall-hook] HTTP {e.code}",
            file=sys.stderr,
        )
    except (urllib.error.URLError, OSError) as e:
        print(f"[recall-hook] 连接失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
