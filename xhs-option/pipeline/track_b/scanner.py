#!/usr/bin/env python3
"""
Track B 每日热帖扫描器
每天早上运行一次，扫描 Twitter/Reddit 上与目标 AI 工具相关的热门帖子，
按「互动量 × 时效性」评分后，将 Top N 写入 state/scans/YYYY-MM-DD.json。
translator.py 读取该文件并翻译成小红书笔记。
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── 路径 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path("/Users/jarvis/xiaohongshu-mcp")
SCAN_DIR    = SCRIPT_DIR / "state" / "scans"
LOG_FILE    = SCRIPT_DIR / "logs" / "scanner.log"
AGENT_REACH = "/Users/jarvis/.local/bin/agent-reach"

_AR_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/Users/jarvis/.local/bin:"
            + os.environ.get("PATH", ""),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─── 扫描目标配置 ──────────────────────────────────────────────────────────────
# Twitter 搜索词：以工具名 + 场景词组合，捕获有实质内容的帖子
TWITTER_QUERIES = [
    # AI 编程 / Claude Code (openclaw_guide / claude_code_guide)
    "OpenClaw tips",
    "Claude Code workflow",
    "Claude Code MCP tools",
    "Claude Code skills tutorial",
    "Cursor tips AI coding",
    # 笔记 / Obsidian (obsidian_guide)
    "Obsidian plugin workflow",
    "Obsidian tips 2026",
    "Obsidian vault setup",
    # 学习 / NotebookLM (ai_tools_learning)
    "NotebookLM tips",
    "NotebookLM use case",
    # 效率综合
    "AI tools productivity workflow",
    "Perplexity tips",
]

# Reddit 搜索词：聚焦有具体内容的社区讨论
REDDIT_QUERIES = [
    # Claude Code (claude_code_guide)
    "Claude Code tips",
    "OpenClaw skills",
    "Claude Code non programmer",
    # Obsidian (obsidian_guide)
    "Obsidian workflow tips",
    "Obsidian beginner setup",
    "Obsidian plugins 2026",
    # 其他
    "NotebookLM tutorial",
    "AI tools comparison 2026",
]

# 最低互动门槛（低于此的帖子不考虑）
MIN_ENGAGEMENT = 50
# 时效性衰减半衰期：48 小时后得分减半
HALFLIFE_HOURS = 48
# 最终输出 Top N
TOP_N = 5


# ─── 核心评分 ─────────────────────────────────────────────────────────────────
def score_post(post: dict, now: datetime) -> float:
    """互动量 × 时效性衰减。帖子越新、互动越高，得分越高。"""
    engagement = post.get("engagement", 0)
    if engagement < MIN_ENGAGEMENT:
        return 0.0

    # agent-reach 不返回发布时间，用扫描时间做近似（所有帖子同等时效）
    # 若未来能拿到 created_at，在此加入衰减
    return float(engagement)


def _run_ar(subcommand: str, query: str, timeout: int = 30) -> list[dict]:
    """调用 agent-reach，解析编号列表输出。"""
    try:
        result = subprocess.run(
            [AGENT_REACH, subcommand, query],
            capture_output=True, text=True,
            timeout=timeout, env=_AR_ENV,
        )
        if result.returncode != 0:
            log.warning("agent-reach %s 失败: %s", subcommand, result.stderr[:200])
            return []
        return _parse_output(result.stdout)
    except subprocess.TimeoutExpired:
        log.warning("agent-reach %s 超时: %s", subcommand, query[:50])
        return []
    except FileNotFoundError:
        log.warning("agent-reach 未找到，跳过 %s", subcommand)
        return []
    except Exception as e:
        log.warning("agent-reach %s 异常 [%s]: %s", subcommand, query[:40], e)
        return []


def _parse_output(text: str) -> list[dict]:
    """解析 agent-reach 编号列表格式。"""
    items = []
    entries = re.split(r'\n(?=\d+\. )', text.strip())
    for entry in entries:
        lines = [l.strip() for l in entry.strip().split('\n') if l.strip()]
        if not lines:
            continue
        title_m = re.match(r'^\d+\.\s+(.+)$', lines[0])
        title = title_m.group(1) if title_m else lines[0]

        url, author, engagement, body_parts = "", "", 0, []
        for line in lines[1:]:
            if line.startswith('🔗'):
                url = line.replace('🔗', '').strip()
            elif line.startswith('👤'):
                parts = re.split(r'·', line.replace('👤', ''))
                author = parts[0].strip()
                for p in parts[1:]:
                    m = re.search(r'([\d,]+)', p)
                    if m:
                        try:
                            engagement = max(engagement, int(m.group(1).replace(',', '')))
                        except ValueError:
                            pass
            else:
                body_parts.append(line)

        if title:
            items.append({
                "title": title,
                "url": url,
                "author": author,
                "engagement": engagement,
                "content": " ".join(body_parts),
            })
    return items


# ─── 主扫描流程 ───────────────────────────────────────────────────────────────
def scan(top_n: int = TOP_N) -> list[dict]:
    now = datetime.now()
    log.info("=" * 50)
    log.info("Track B 扫描开始 @ %s", now.strftime("%Y-%m-%d %H:%M"))

    all_posts: list[dict] = []
    seen_urls: set[str] = set()

    # Twitter
    log.info("── Twitter 扫描（%d 个查询）", len(TWITTER_QUERIES))
    for query in TWITTER_QUERIES:
        posts = _run_ar("search-twitter", query, timeout=30)
        for p in posts:
            key = p.get("url") or p["title"]
            if key in seen_urls:
                continue
            seen_urls.add(key)
            p["source"] = "Twitter"
            p["query"] = query
            all_posts.append(p)
        log.info("  [Twitter] '%s' → %d 条", query[:40], len(posts))

    # Reddit
    log.info("── Reddit 扫描（%d 个查询）", len(REDDIT_QUERIES))
    for query in REDDIT_QUERIES:
        posts = _run_ar("search-reddit", query, timeout=30)
        for p in posts:
            key = p.get("url") or p["title"]
            if key in seen_urls:
                continue
            seen_urls.add(key)
            p["source"] = "Reddit"
            p["query"] = query
            all_posts.append(p)
        log.info("  [Reddit] '%s' → %d 条", query[:40], len(posts))

    log.info("共采集 %d 条原始帖子", len(all_posts))

    # 评分 + 排序
    for p in all_posts:
        p["score"] = score_post(p, now)

    ranked = sorted(
        [p for p in all_posts if p["score"] > 0],
        key=lambda x: x["score"],
        reverse=True,
    )

    top = ranked[:top_n]
    log.info("Top %d 帖子（按评分）:", len(top))
    for i, p in enumerate(top, 1):
        log.info("  %d. [%s] %s (互动=%d)", i, p["source"], p["title"][:50], p["engagement"])

    return top


def save_results(posts: list[dict]) -> Path:
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out = SCAN_DIR / f"{today}.json"
    out.write_text(
        json.dumps({
            "date": today,
            "scanned_at": datetime.now().isoformat(timespec="seconds"),
            "posts": posts,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("扫描结果已保存: %s", out)
    return out


def main():
    top_posts = scan()
    if top_posts:
        save_results(top_posts)
        log.info("✅ 扫描完成，%d 篇待翻译", len(top_posts))
    else:
        log.warning("⚠️ 未找到合格帖子，可能网络问题或 agent-reach 故障")


if __name__ == "__main__":
    main()
