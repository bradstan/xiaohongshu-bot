#!/usr/bin/env python3
"""
全自动内容生产脚本
1. 搜索小红书 + Web（Reddit/X/财经网站）获取热门话题和素材
2. 结合历史数据分析，选定本批选题方向
3. 调用 Claude CLI 生成完整文章
4. 输出到「待发布/」文件夹，等待 publish.py 自动发布
"""

import json
import re
import sys
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
import urllib.request
import urllib.error

# ─── 配置 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path("/Users/jarvis/xiaohongshu-mcp")
TOPICS_FILE   = SCRIPT_DIR / "topics.json"
STATE_FILE    = SCRIPT_DIR / "published.json"
LOG_FILE      = SCRIPT_DIR / "research.log"
PUBLISH_DIR   = Path("/Users/jarvis/Documents/小红书/待发布")
MCP_URL       = "http://localhost:18060/mcp"
MCP_ACCEPT    = "application/json, text/event-stream"
CLAUDE_BIN    = "/Users/jarvis/.npm-global/bin/claude"

# ─── 日志 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ─── MCP 调用 ─────────────────────────────────────────────────────────────────
_session_id: Optional[str] = None


def get_session() -> str:
    global _session_id
    if _session_id:
        return _session_id
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "research", "version": "1.0"},
        },
    }).encode()
    req = urllib.request.Request(
        MCP_URL, data=payload,
        headers={"Content-Type": "application/json", "Accept": MCP_ACCEPT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        sid = resp.headers.get("mcp-session-id", "")
        resp.read()
    if not sid:
        raise RuntimeError("MCP server 未返回 session ID")
    _session_id = sid
    return sid


def mcp_call(method: str, params: dict, req_id: int = 2) -> dict:
    sid = get_session()
    payload = json.dumps({
        "jsonrpc": "2.0", "id": req_id, "method": method, "params": params
    }).encode()
    req = urllib.request.Request(
        MCP_URL, data=payload,
        headers={"Content-Type": "application/json", "Accept": MCP_ACCEPT, "mcp-session-id": sid},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def call_tool(tool_name: str, arguments: dict) -> dict:
    return mcp_call("tools/call", {"name": tool_name, "arguments": arguments})


def check_mcp_alive() -> bool:
    try:
        get_session()
        return True
    except Exception as e:
        log.error("MCP server 不可达: %s", e)
        return False


# ─── 数据读取 ─────────────────────────────────────────────────────────────────
def load_topics() -> dict:
    with TOPICS_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"published": []}
    with STATE_FILE.open(encoding="utf-8") as f:
        return json.load(f)


# ─── 历史数据分析 ─────────────────────────────────────────────────────────────
def analyze_past_performance(state: dict) -> dict:
    """返回各已发文章的最新互动数据"""
    performance = {}
    for entry in state.get("published", []):
        cp = entry.get("checkpoints", {})
        data = {}
        for label in ["24小时", "6小时", "3小时", "1小时", "30分钟"]:
            if label in cp:
                data = cp[label]
                break
        if not data:
            continue
        performance[entry.get("title", "")] = {
            "collected": data.get("collected", 0),
            "liked": data.get("liked", 0),
        }
    return performance


def get_published_titles(state: dict) -> List[str]:
    """获取所有已发布文章标题，用于去重"""
    titles = []
    for entry in state.get("published", []):
        if entry.get("title"):
            titles.append(entry["title"])
    return titles


def get_pending_titles() -> List[str]:
    """获取所有待发布文章标题，用于去重"""
    titles = []
    for f in PUBLISH_DIR.glob("*.md"):
        # 从文件名提取标题（去掉日期前缀和版本后缀）
        name = f.stem
        # 去掉日期前缀 YYYY-MM-DD｜
        name = re.sub(r'^\d{4}-\d{2}-\d{2}[｜|]', '', name)
        titles.append(name)
    return titles


# ─── 小红书搜索（限一周内） ───────────────────────────────────────────────────
def get_feed_content(feed_id: str, xsec_token: str) -> Optional[str]:
    """获取笔记正文内容"""
    try:
        result = call_tool("get_feed_detail", {
            "feed_id": feed_id,
            "xsec_token": xsec_token,
        })
        note = result.get("data", {}).get("note", {})
        desc = note.get("desc", "")
        return desc if desc else None
    except Exception as e:
        log.warning("获取笔记详情失败: %s", e)
        return None


def search_xiaohongshu_with_content(keyword: str, max_notes: int = 3) -> List[dict]:
    """搜索小红书一周内的热门内容，包含笔记正文"""
    try:
        result = call_tool("search_feeds", {
            "keyword": keyword,
            "filters": {"sort_by": "最多收藏", "publish_time": "一周内"}
        })
        text = ""
        inner = result.get("result", {}).get("content", [])
        if inner:
            text = inner[0].get("text", "")
        try:
            data = json.loads(text)
        except Exception:
            data = {}
        feeds = data.get("feeds", [])

        notes = []
        for feed in feeds[:max_notes]:
            note_card = feed.get("noteCard", {})
            title = note_card.get("displayTitle", "") or note_card.get("title", "")
            interact = note_card.get("interactInfo", {})
            feed_id = feed.get("id", "")
            xsec_token = feed.get("xsecToken", "")

            if not title or not feed_id:
                continue

            content = get_feed_content(feed_id, xsec_token)

            notes.append({
                "title": title,
                "content": content or "",
                "collected": interact.get("collectedCount", "0"),
                "liked": interact.get("likedCount", "0"),
                "source": "小红书(本周)",
            })
        return notes
    except Exception as e:
        log.warning("小红书搜索 [%s] 失败: %s", keyword, e)
        return []


# ─── Web 搜索（最新新闻 + Reddit/X） ─────────────────────────────────────────
TAVILY_API_KEY = "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"
TAVILY_URL     = "https://api.tavily.com/search"


def search_web(query: str, max_results: int = 5) -> List[dict]:
    """
    用 Tavily Search API 搜索最新内容。
    Tavily 自动过滤时效性，返回近期结果。
    """
    try:
        payload = json.dumps({
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }).encode()
        req = urllib.request.Request(
            TAVILY_URL, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "content": item.get("content", "")[:600],
                "url": item.get("url", ""),
                "source": "Web",
            })
        return results
    except Exception as e:
        log.warning("Web 搜索 [%s] 失败: %s", query, e)
        return []


def fetch_market_context(theme: dict) -> dict:
    """
    搜集与主题相关的最新市场数据：
    1. TSLA 当前股价 + 最新新闻
    2. Reddit/X 上的热门讨论
    返回结构化的上下文信息
    """
    context = {"news": [], "reddit": [], "price_info": ""}

    # 1. 最新新闻 + 股价
    keywords = theme.get("keywords", [])
    main_kw = keywords[0] if keywords else theme.get("name", "")
    news = search_web(f"Tesla TSLA {main_kw} latest news today {datetime.now().strftime('%Y')}")
    context["news"] = news
    log.info("  Web 新闻 %d 条", len(news))

    # 2. Reddit 讨论
    reddit = search_web(f"site:reddit.com Tesla TSLA options {main_kw} {datetime.now().strftime('%Y-%m')}")
    context["reddit"] = reddit
    log.info("  Reddit 参考 %d 条", len(reddit))

    # 3. 当前股价（从新闻结果中提取，或单独搜）
    price_results = search_web("TSLA Tesla stock price today", max_results=2)
    if price_results:
        context["price_info"] = price_results[0].get("content", "")[:300]
    log.info("  股价数据: %s", "已获取" if context["price_info"] else "未获取")

    return context


# ─── Claude CLI 调用 ──────────────────────────────────────────────────────────
def call_claude(prompt: str, max_tokens: int = 4096) -> Optional[str]:
    """调用 claude CLI 的 --print 模式生成文本"""
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--print", "--max-turns", "1"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            log.warning("Claude CLI 错误: %s", result.stderr[:500])
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.warning("Claude CLI 超时")
        return None
    except Exception as e:
        log.warning("Claude CLI 调用失败: %s", e)
        return None


# ─── 选题决策 ─────────────────────────────────────────────────────────────────
def pick_themes(topics_config: dict, performance: dict,
                published_titles: List[str], pending_titles: List[str],
                notes_needed: int) -> List[dict]:
    """
    从主题池中选出本批要写的主题。
    优先选：1) 历史收藏高的方向  2) 还没覆盖过的方向
    """
    themes = topics_config.get("themes", [])
    if not themes:
        return []

    # 统计各主题已发篇数
    theme_counts = {t["id"]: 0 for t in themes}
    all_titles = published_titles + pending_titles
    for title in all_titles:
        for theme in themes:
            for kw in theme.get("keywords", []):
                if kw.lower() in title.lower():
                    theme_counts[theme["id"]] += 1
                    break

    # 按已发篇数升序排列（少的优先），保证覆盖均匀
    sorted_themes = sorted(themes, key=lambda t: theme_counts.get(t["id"], 0))

    return sorted_themes[:notes_needed]


# ─── 文章生成 ─────────────────────────────────────────────────────────────────
def generate_article(theme: dict, xhs_refs: List[dict],
                     market_ctx: dict, performance: dict,
                     topics_config: dict, now: datetime) -> Optional[dict]:
    """
    给定主题、小红书参考、实时市场数据，调用 Claude 生成一篇完整文章。
    返回 {"title": ..., "content": ..., "filename": ...} 或 None
    """
    account_desc = topics_config.get("account_description", "")
    target_audience = topics_config.get("target_audience", "")
    content_style = topics_config.get("content_style", "")

    # 小红书参考（只取写法风格，不取数据）
    xhs_style_text = ""
    for i, ref in enumerate(xhs_refs, 1):
        xhs_style_text += f"\n--- 写法参考{i}（{ref['source']}，收藏{ref['collected']}）---\n"
        xhs_style_text += f"标题：{ref['title']}\n"
        if ref.get("content"):
            xhs_style_text += f"正文摘要：{ref['content'][:500]}\n"

    # 最新新闻
    news_text = ""
    for i, n in enumerate(market_ctx.get("news", []), 1):
        news_text += f"\n--- 新闻{i} ---\n标题：{n['title']}\n内容：{n['content']}\n"

    # Reddit 讨论
    reddit_text = ""
    for i, r in enumerate(market_ctx.get("reddit", []), 1):
        reddit_text += f"\n--- Reddit{i} ---\n标题：{r['title']}\n内容：{r['content']}\n"

    # 当前股价
    price_info = market_ctx.get("price_info", "暂无数据")

    # 历史表现
    perf_text = ""
    if performance:
        sorted_perf = sorted(performance.items(), key=lambda x: x[1]["collected"], reverse=True)
        for title, d in sorted_perf[:3]:
            perf_text += f"- 「{title}」收藏{d['collected']} 点赞{d['liked']}\n"

    prompt = f"""你是一个小红书内容创作专家。请根据以下信息，创作一篇完整的小红书笔记。

## ⚠️ 关键要求

### 时效性
- 今天是 {now.strftime('%Y年%m月%d日')}
- 文章中的所有数据（股价、事件、新闻）必须来自下方提供的【最新市场数据】
- 禁止使用任何过时的股价或事件（比如去年的价格区间）
- 如果不确定某个数据是否最新，就不要写具体数字

### 合规红线（必须遵守）
- 禁止虚构任何交易记录、持仓信息、盈亏数据——我们没有真实持仓可以分享
- 禁止出现"我的操作"、"我的持仓"、"我买了/卖了"等第一人称交易描述
- 禁止给出具体的买卖建议（如"现在应该买入XX"），只做策略分析和教育科普
- 对新闻事件只客观陈述事实，不要擅自判断利好/利空，可以分析"如果...那么..."的场景
- 文末加免责声明：本文仅为知识分享，不构成投资建议

## 当前市场数据
**TSLA 最新股价信息：**
{price_info}

**最新新闻（本周）：**
{news_text if news_text else '暂无最新新闻'}

**Reddit/X 热门讨论：**
{reddit_text if reddit_text else '暂无讨论'}

## 账号定位
- 描述：{account_desc}
- 目标受众：{target_audience}
- 内容风格：{content_style}

## 本篇主题方向
- 主题：{theme['name']}
- 说明：{theme['description']}
- 关键词：{', '.join(theme.get('keywords', []))}

## 小红书热门写法参考（仅参考标题风格和结构，不要复制内容）
{xhs_style_text if xhs_style_text else '暂无参考'}

## 历史表现最好的文章（供参考风格方向）
{perf_text if perf_text else '暂无历史数据'}

## 写作要求
1. 标题：20字以内，数字冲击感+痛点/悬念
2. 正文：800-1000字（不超过1000字，小红书限制）
3. 开头3行抓人：最新数据hook、痛点共鸣、或反常识观点
4. 结构清晰：用 ## 小标题分段，**粗体**强调关键信息
5. 实战导向：用上方提供的最新数据，有具体数字和操作步骤
6. 结尾互动：问一个具体问题引导评论
7. 标签：文末8-10个标签（#话题#格式）

## 输出格式
请严格按照以下格式输出，不要有任何额外说明：

---
tags: [小红书, 投资]
date: {now.strftime('%Y-%m-%d')}
version: v1.0
---

# 小红书标题（这里写标题）

正文内容...

---

*标签：#标签1 #标签2 ...*
*版本：v1.0*
"""

    log.info("调用 Claude 生成文章: %s", theme["name"])
    article = call_claude(prompt)
    if not article:
        return None

    # 从生成内容中提取标题
    title_match = re.search(r'^#\s+(.+)$', article, re.MULTILINE)
    if not title_match:
        log.warning("无法从生成内容中提取标题")
        return None

    raw_title = title_match.group(1).strip()

    # 计算正文字数（去掉 frontmatter、标题行、标签行、分隔线）
    body = article
    body = re.sub(r'^---\n.*?\n---\n', '', body, count=1, flags=re.DOTALL)  # frontmatter
    body = re.sub(r'^#\s+.+\n', '', body, count=1, flags=re.MULTILINE)      # 标题行
    body = re.sub(r'^\*标签：.+\*$', '', body, flags=re.MULTILINE)           # 标签行
    body = re.sub(r'^\*版本：.+\*$', '', body, flags=re.MULTILINE)           # 版本行
    body = re.sub(r'^---+$', '', body, flags=re.MULTILINE)                   # 分隔线
    word_count = len(re.sub(r'\s+', '', body))

    # 在 frontmatter 中插入 word_count
    article = re.sub(
        r'^(---\ntags:.*?\ndate:.*?\nversion:.*?)\n---',
        rf'\1\nword_count: {word_count}\n---',
        article,
        count=1,
        flags=re.DOTALL,
    )

    # 清理标题中的特殊字符，用于文件名
    safe_title = re.sub(r'[/\\:*?"<>|]', '', raw_title)
    safe_title = re.sub(r'\s+', '', safe_title)[:30]

    filename = f"{now.strftime('%Y-%m-%d')}｜{safe_title}.md"

    return {
        "title": raw_title,
        "content": article,
        "filename": filename,
    }


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=" * 50)
    log.info("全自动内容生产 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not check_mcp_alive():
        log.error("MCP server 不可达，退出")
        return

    now = datetime.now()
    topics_config = load_topics()
    state = load_state()

    # 分析历史数据
    performance = analyze_past_performance(state)
    published_titles = get_published_titles(state)
    pending_titles = get_pending_titles()
    log.info("已发布 %d 篇，待发布 %d 篇", len(published_titles), len(pending_titles))

    # 计算还需要生成几篇（每周目标 - 待发布库存）
    posts_per_week = topics_config.get("posts_per_week", 7)
    notes_needed = max(0, posts_per_week - len(pending_titles))
    if notes_needed == 0:
        log.info("待发布库存充足（%d 篇），本次不生成新内容", len(pending_titles))
        return
    log.info("需要生成 %d 篇新内容", notes_needed)

    # 选定主题
    selected_themes = pick_themes(
        topics_config, performance,
        published_titles, pending_titles,
        notes_needed,
    )
    log.info("选定 %d 个主题: %s", len(selected_themes),
             ", ".join(t["name"] for t in selected_themes))

    # 逐主题：搜索素材 → 获取实时数据 → 生成文章 → 保存
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    generated = 0
    for theme in selected_themes:
        keyword = theme["keywords"][0]

        # 1. 搜索小红书本周热门（写法参考）
        log.info("搜索小红书素材: %s", keyword)
        xhs_refs = search_xiaohongshu_with_content(keyword, max_notes=3)
        log.info("  小红书参考 %d 条", len(xhs_refs))

        # 2. 搜索 Web 最新数据（新闻 + Reddit + 股价）
        log.info("搜索 Web 实时数据: %s", theme["name"])
        market_ctx = fetch_market_context(theme)

        # 3. 生成文章
        article = generate_article(theme, xhs_refs, market_ctx,
                                   performance, topics_config, now)
        if not article:
            log.warning("文章生成失败: %s", theme["name"])
            continue

        # 保存到待发布
        out_path = PUBLISH_DIR / article["filename"]
        out_path.write_text(article["content"], encoding="utf-8")
        log.info("✓ 已保存: %s", article["filename"])
        generated += 1

    log.info("=" * 50)
    log.info("本次生成 %d 篇文章，已放入待发布文件夹", generated)


if __name__ == "__main__":
    main()
