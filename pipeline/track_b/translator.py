#!/usr/bin/env python3
"""
Track B 翻译器
读取今日扫描结果（state/scans/YYYY-MM-DD.json），
逐篇调用 Claude 翻译 + 本土化，输出到 vault/待发布/。

Track B 内容时效性强，跳过人工审核，直接进入发布队列。
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── 路径 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path("/Users/jarvis/xiaohongshu-mcp")
SCAN_DIR     = SCRIPT_DIR / "state" / "scans"
PUBLISH_DIR  = Path("/Users/jarvis/xiaohongshu-mcp/vault/待发布")
LOG_FILE     = SCRIPT_DIR / "logs" / "translator.log"

sys.path.insert(0, str(SCRIPT_DIR))
from llm import call_llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─── QA 规则（轻量，Track B 优先时效性） ─────────────────────────────────────
MAX_CHARS = 650     # 正文字符上限（含标签前）
MIN_CHARS = 150     # 过短说明生成失败


def _qa_check(article: str) -> tuple[bool, str]:
    """返回 (通过, 原因)。"""
    # 提取正文（去掉 frontmatter + 标题行）
    body = re.sub(r'^---\n.*?\n---\n', '', article, count=1, flags=re.DOTALL)
    body = re.sub(r'^#\s+.+\n', '', body, count=1, flags=re.MULTILINE)
    body = re.sub(r'^#[\w\u4e00-\u9fff#\s]+$', '', body, flags=re.MULTILINE)  # 标签行
    body = re.sub(r'^---+$', '', body, flags=re.MULTILINE)
    char_count = len(re.sub(r'\s+', '', body))

    if char_count < MIN_CHARS:
        return False, f"正文过短（{char_count}字）"
    if char_count > MAX_CHARS:
        return False, f"正文超限（{char_count}字 > {MAX_CHARS}）"
    if not re.search(r'^#\s+.+', article, re.MULTILINE):
        return False, "缺少标题行"
    return True, "OK"


# ─── 翻译 Prompt ──────────────────────────────────────────────────────────────
def _build_prompt(post: dict, now: datetime) -> str:
    source      = post.get("source", "Twitter")
    author      = post.get("author", "未知作者")
    engagement  = post.get("engagement", 0)
    title       = post.get("title", "")
    content     = post.get("content", "")
    url         = post.get("url", "")

    # 构建署名行：来自 Twitter @xxx 或 Reddit u/xxx
    if author and author not in ("未知作者", "unknown", ""):
        if "reddit" in source.lower():
            attribution = f"（来自 Reddit u/{author}）"
        else:
            attribution = f"（来自 X @{author}）"
    else:
        attribution = f"（来自 {source}）"

    return f"""你是一个专注 AI 工具领域的中文内容创作者，面向小红书用户（25-35岁，爱学新工具的职场人）。

## 原帖信息
- 来源：{source}
- 作者：{author}（{engagement} 互动）
- 链接：{url}
- 标题：{title}
- 正文摘要：{content}

## 你的任务：翻译 + 本土化

把这条帖子改写成小红书笔记。**不是重新创作，是忠实翻译后加中国视角。**

### 保留原帖的核心价值
- 它为什么让人停下来看？（hook）
- 最有用的那个信息点是什么？
- 如果有步骤，完整保留，不得夸大或改编功能描述

### 加入中国读者视角（选1-2点加，不要全加）
- 国内有没有类似替代品？差在哪？
- 这个用法在哪个中国场景特别实用？（比如处理中文、微信场景等）
- 国内用户容易遇到的坑（网络、账号限制等）

### ⚠️ 内容红线
- **禁止**承诺"全程图文"、"附截图"——我们没有真实截图
- **禁止**推荐原帖中未提到的工具/插件/功能
- **禁止**写"我亲测"等无来源的个人体验（你是翻译者，不是测试者）
- 如果原帖有具体操作步骤，完整保留，不要自己发明新步骤

### 写作风格
像一个刚发现好东西的朋友在朋友圈分享：
- 自然口语，不要正式书面语
- 不写"值得一提的是"、"总的来说"这类套话
- 段落之间要有承接，不要硬切

### Bullet points 要求（必须执行）
正文中必须包含 **最少1段、最多2段** bullet points（`-` 开头的列表）。
用于承载并列要点，如步骤、判断标准、注意事项。
列表前后须有散文句子承接，不能让列表孤立漂浮。

### 字数控制
正文 250-500 字（不含标签和署名）。超过就删次要内容，不要压缩核心信息点。

## 输出格式（严格遵守）

---
tags: [AI工具]
date: {now.strftime('%Y-%m-%d')}
version: v1.0
category: ai_tools
source_url: {url}
source_author: {author}
---

# 标题（20字以内，突出最有价值的那个点，可以用数字或反常识）

正文内容...

{attribution}

---

#标签1 #标签2 #标签3 #标签4 #标签5 #标签6 #标签7 #标签8

⚠️ 仅为工具分享，效果因人因场景而异。
"""


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def translate_post(post: dict, now: datetime) -> Optional[dict]:
    prompt = _build_prompt(post, now)
    log.info("翻译: %s", post.get("title", "")[:60])

    article = call_llm(prompt, max_tokens=2048)
    if not article:
        log.warning("LLM 返回为空")
        return None

    # 注入 theme_id（按内容关键词自动路由到对应主题）
    raw = (post.get("title", "") + " " + post.get("content", "")).lower()
    if any(k in raw for k in ["obsidian", "双链", "vault", "dataview", "templater"]):
        theme_id = "obsidian_guide"
    elif any(k in raw for k in ["claude code", "openclaw", "claude-code", "mcp server", "claude skills"]):
        theme_id = "claude_code_guide"
    else:
        theme_id = "ai_tools_learning"

    article = re.sub(
        r'^(---\ntags:.*?\ncategory:\s*ai_tools)',
        rf'\1\ntheme_id: {theme_id}',
        article, count=1, flags=re.DOTALL,
    )

    ok, reason = _qa_check(article)
    if not ok:
        log.warning("QA 不通过（%s），尝试精简...", reason)
        trim_prompt = f"""以下文章正文超出字数限制或格式有误（{reason}）。
请在保持格式（frontmatter + 标题 + 正文 + 免责声明 + 标签）不变的前提下精简正文到500字以内。
直接输出修改后的完整文章，不要说明。

{article}"""
        article = call_llm(trim_prompt, max_tokens=2048) or article
        ok, reason = _qa_check(article)
        if not ok:
            log.warning("精简后仍不通过（%s），跳过此帖", reason)
            return None

    # 提取标题
    title_m = re.search(r'^#\s+(.+)$', article, re.MULTILINE)
    if not title_m:
        log.warning("无法提取标题，跳过")
        return None
    raw_title = title_m.group(1).strip()

    safe_title = re.sub(r'[/\\:*?"<>|]', '', raw_title)
    safe_title = re.sub(r'\s+', '', safe_title)[:30]
    filename = f"{now.strftime('%Y-%m-%d')}｜{safe_title}.md"

    return {
        "title": raw_title,
        "content": article,
        "filename": filename,
        "source_url": post.get("url", ""),
    }


def load_today_scan() -> Optional[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    scan_file = SCAN_DIR / f"{today}.json"
    if not scan_file.exists():
        log.warning("今日扫描文件不存在: %s", scan_file)
        return None
    return json.loads(scan_file.read_text(encoding="utf-8"))


def main(max_translate: int = 2):
    """
    默认每次只翻译 Top 2，保持每日内容节奏。
    通过 --count 参数可覆盖。
    """
    log.info("=" * 50)
    log.info("Track B 翻译开始 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M"))

    scan_data = load_today_scan()
    if not scan_data:
        return

    posts = scan_data.get("posts", [])
    if not posts:
        log.info("今日扫描结果为空，跳过")
        return

    log.info("今日扫描帖子 %d 篇，翻译 Top %d", len(posts), max_translate)
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    translated = 0

    for post in posts[:max_translate]:
        result = translate_post(post, now)
        if not result:
            continue

        out_path = PUBLISH_DIR / result["filename"]
        out_path.write_text(result["content"], encoding="utf-8")
        log.info("✓ 已写入待发布: %s", result["filename"])
        translated += 1

    log.info("=" * 50)
    log.info("本次翻译 %d 篇，已放入待发布", translated)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=2,
                        help="本次翻译篇数（默认 2）")
    args = parser.parse_args()
    main(max_translate=args.count)
