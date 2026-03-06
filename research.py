#!/usr/bin/env python3
"""
全自动内容生产脚本
1. 搜索小红书 + Web（Reddit/X/财经网站）获取热门话题和素材
2. 结合历史数据分析，选定本批选题方向
3. 调用 Claude CLI 生成完整文章
4. 输出到「待发布/」文件夹，等待 publish.py 自动发布
"""

import json
import os
import re
import sys
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
import urllib.request
import urllib.error

# cron 环境没有用户 PATH，确保 Homebrew 路径可用（node/yt-dlp 等依赖）
if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

# ─── 配置 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent
TOPICS_FILE   = SCRIPT_DIR / "topics.json"
STATE_FILE    = SCRIPT_DIR / "published.json"
LOG_FILE      = SCRIPT_DIR / "research.log"
PUBLISH_DIR   = SCRIPT_DIR / "vault" / "待发布"
MCP_URL       = "http://localhost:18060/mcp"
MCP_ACCEPT    = "application/json, text/event-stream"
# Claude CLI 已迁移到 llm.py 统一模块

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
    """返回各已发文章的完整互动数据（含 theme_id、增长趋势）"""
    performance = {}
    for entry in state.get("published", []):
        cp = entry.get("checkpoints", {})
        # 取最新时间点数据
        latest = {}
        for label in ["24小时", "6小时", "3小时", "1小时", "30分钟"]:
            if label in cp:
                latest = cp[label]
                break
        if not latest:
            continue
        # 计算增长趋势（30min → latest）
        early = cp.get("30分钟", {})
        velocity = {
            "collected_growth": latest.get("collected", 0) - early.get("collected", 0),
            "liked_growth": latest.get("liked", 0) - early.get("liked", 0),
        }
        performance[entry.get("title", "")] = {
            "theme_id":  entry.get("theme_id", "unknown"),
            "collected": latest.get("collected", 0),
            "liked":     latest.get("liked", 0),
            "comment":   latest.get("comment", 0),
            "shared":    latest.get("shared", 0),
            "velocity":  velocity,
        }
    return performance


def load_latest_review() -> str:
    """读取最新复盘文件的优化建议部分，供 Claude 参考"""
    review_dir = SCRIPT_DIR / "vault" / "已发布" / "复盘"
    if not review_dir.exists():
        return ""
    reviews = sorted(review_dir.glob("*复盘.md"), reverse=True)
    if not reviews:
        return ""
    try:
        text = reviews[0].read_text(encoding="utf-8")
        # 提取第三章（优化建议/可执行优化）到文件末尾之间的内容
        match = re.search(r'## 三、[^\n]+\n(.*?)(?=---\n\*自动生成|$)', text, re.DOTALL)
        if match:
            content = match.group(1).strip()
            # 跳过空占位符
            if "待AI分析" in content or "待手动填写" in content:
                return ""
            return content[:2000]  # 限制长度
    except Exception:
        pass
    return ""


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


# ─── 多平台素材采集（x-reader 风格） ───────────────────────────────────────────
from collectors import collect_all, materials_to_prompt_text


# ─── 以下旧采集代码已废弃，保留 get_feed_content 供 feedback.py 兼容 ─────────
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


def _search_xhs_single(keyword: str, sort_by: str, max_notes: int) -> List[dict]:
    """单次小红书搜索，返回笔记列表"""
    try:
        result = call_tool("search_feeds", {
            "keyword": keyword,
            "filters": {"sort_by": sort_by, "publish_time": "一周内"}
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
        seen_ids = set()
        for feed in feeds[:max_notes]:
            note_card = feed.get("noteCard", {})
            title = note_card.get("displayTitle", "") or note_card.get("title", "")
            interact = note_card.get("interactInfo", {})
            feed_id = feed.get("id", "")
            xsec_token = feed.get("xsecToken", "")

            if not title or not feed_id or feed_id in seen_ids:
                continue
            seen_ids.add(feed_id)

            content = get_feed_content(feed_id, xsec_token)

            notes.append({
                "title": title,
                "content": content or "",
                "collected": interact.get("collectedCount", "0"),
                "liked": interact.get("likedCount", "0"),
                "source": f"小红书({sort_by})",
            })
        return notes
    except Exception as e:
        log.warning("小红书搜索 [%s/%s] 失败: %s", keyword, sort_by, e)
        return []


def search_xiaohongshu_with_content(keywords: List[str], max_total: int = 20) -> List[dict]:
    """
    用多个关键词 × 多个排序维度搜索小红书，去重后返回 max_total 条。
    每个关键词分别按「最多收藏」和「最多点赞」搜索，扩大覆盖面。
    """
    all_notes = []
    seen_titles = set()
    per_query = max(5, max_total // max(len(keywords) * 2, 1))

    for kw in keywords:
        for sort_by in ["最多收藏", "最多点赞"]:
            batch = _search_xhs_single(kw, sort_by, per_query)
            for note in batch:
                # 按标题去重
                clean = re.sub(r'\s+', '', note["title"])
                if clean not in seen_titles:
                    seen_titles.add(clean)
                    all_notes.append(note)
            if len(all_notes) >= max_total:
                break
        if len(all_notes) >= max_total:
            break

    # 按收藏数降序排列，取 top N
    all_notes.sort(key=lambda x: int(str(x.get("collected", 0)).replace(",", "") or 0), reverse=True)
    return all_notes[:max_total]


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
    1. TSLA 当前股价 + 最新新闻（多轮搜索，至少20条）
    2. Reddit/X 上的热门讨论（多轮搜索，至少20条）
    返回结构化的上下文信息
    """
    context = {"news": [], "reddit": [], "price_info": ""}

    keywords = theme.get("keywords", [])
    main_kw = keywords[0] if keywords else theme.get("name", "")
    year = datetime.now().strftime('%Y')
    month = datetime.now().strftime('%Y-%m')

    # 1. 最新新闻（多轮搜索，不同角度，合计 20 条）
    news_queries = [
        f"Tesla TSLA {main_kw} latest news today {year}",
        f"TSLA options market {main_kw} {year}",
        f"Tesla stock analysis {main_kw} this week {year}",
        f"TSLA earnings outlook {main_kw} {year}",
    ]
    all_news = []
    seen_urls = set()
    for q in news_queries:
        batch = search_web(q, max_results=10)
        for item in batch:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_news.append(item)
        if len(all_news) >= 20:
            break
    context["news"] = all_news[:20]
    log.info("  Web 新闻 %d 条", len(context["news"]))

    # 2. Reddit 讨论（多轮搜索，合计 20 条）
    reddit_queries = [
        f"site:reddit.com Tesla TSLA options {main_kw} {month}",
        f"site:reddit.com TSLA call put strategy {month}",
        f"site:reddit.com r/options TSLA {main_kw} {year}",
        f"site:reddit.com r/wallstreetbets TSLA {year}",
    ]
    all_reddit = []
    seen_reddit_urls = set()
    for q in reddit_queries:
        batch = search_web(q, max_results=10)
        for item in batch:
            if item["url"] not in seen_reddit_urls:
                seen_reddit_urls.add(item["url"])
                item["source"] = "Reddit"
                all_reddit.append(item)
        if len(all_reddit) >= 20:
            break
    context["reddit"] = all_reddit[:20]
    log.info("  Reddit 参考 %d 条", len(context["reddit"]))

    # 3. 当前股价
    price_results = search_web("TSLA Tesla stock price today", max_results=3)
    if price_results:
        context["price_info"] = price_results[0].get("content", "")[:500]
    log.info("  股价数据: %s", "已获取" if context["price_info"] else "未获取")

    return context


# ─── LLM 调用（统一模块） ────────────────────────────────────────────────────
from llm import call_llm


def call_claude(prompt: str, max_tokens: int = 4096) -> Optional[str]:
    """调用 LLM 生成文本（兼容旧接口名）"""
    return call_llm(prompt, max_tokens=max_tokens)


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
def generate_article(theme: dict, ref_text: str,
                     performance: dict,
                     topics_config: dict, now: datetime) -> Optional[dict]:
    """
    给定主题和多源参考素材，调用 Claude 生成一篇期权知识科普文章。
    返回 {"title": ..., "content": ..., "filename": ...} 或 None
    """
    account_desc = topics_config.get("account_description", "")
    target_audience = topics_config.get("target_audience", "")
    content_style = topics_config.get("content_style", "")

    # 历史表现（丰富版：含主题维度+增长趋势+失败分析）
    perf_text = ""
    if performance:
        sorted_perf = sorted(performance.items(), key=lambda x: x[1]["collected"], reverse=True)
        # Top5 排名
        perf_text += "### 表现排名（按收藏排序）\n"
        for title, d in sorted_perf[:5]:
            perf_text += (f"- 「{title}」[{d['theme_id']}] "
                          f"收藏{d['collected']} 点赞{d['liked']} "
                          f"评论{d['comment']} 分享{d['shared']}\n")
        # 主题维度
        theme_stats = {}
        for title, d in performance.items():
            tid = d["theme_id"]
            if tid not in theme_stats:
                theme_stats[tid] = {"total_collected": 0, "count": 0}
            theme_stats[tid]["total_collected"] += d["collected"]
            theme_stats[tid]["count"] += 1
        perf_text += "\n### 主题维度表现\n"
        for tid, stats in sorted(theme_stats.items(), key=lambda x: x[1]["total_collected"], reverse=True):
            avg = stats["total_collected"] / stats["count"]
            perf_text += f"- {tid}: 平均收藏{avg:.0f}（{stats['count']}篇）\n"
        # 失败分析
        if len(sorted_perf) > 2:
            perf_text += "\n### 表现较差的内容（需避开类似方向）\n"
            for title, d in sorted_perf[-2:]:
                perf_text += f"- 「{title}」收藏{d['collected']} 点赞{d['liked']}\n"

    # 读取最新复盘的优化建议
    review_insights = load_latest_review()
    review_section = ""
    if review_insights:
        review_section = f"\n## 上一轮复盘的优化建议（重点参考！）\n{review_insights}\n"

    prompt = f"""你是一个小红书期权知识科普创作专家。请根据以下信息，创作一篇完整的小红书笔记。

## ⚠️ 核心定位：知识科普

这是一个**期权知识科普**账号，不是财经资讯账号。文章目的是**教会读者一个期权概念或策略**。

### 数据使用规则（极其重要！）
- **禁止引用任何真实的市场数据**：不写真实股价、真实财报数字、真实涨跌幅
- **禁止引用真实事件作为论据**：不写"XX日财报显示..."、"上周XX消息..."
- 举例时用**假设场景**：「假设某只股票当前价格100美元...」「假设你看好某只科技股...」
- 可以用TSLA、AAPL、NVDA等热门股票**举例说明概念**，但不要写它们的真实价格
- 举例的数字要**合理但明确是假设**：用整数（如100美元、50美元），避免写得像真实数据（如411.82美元）

### 合规红线
- 禁止虚构交易记录、持仓信息、盈亏数据
- 禁止"我买了/卖了"等第一人称交易描述
- 禁止给出具体买卖建议，只做概念讲解和策略科普
- 文末加一句：「⚠️ 仅为知识分享，不构成投资建议。」

## 账号定位
- 描述：{account_desc}
- 目标受众：{target_audience}
- 内容风格：{content_style}

## 本篇主题方向
- 主题：{theme['name']}
- 说明：{theme['description']}
- 关键词：{', '.join(theme.get('keywords', []))}

## 多平台素材参考（学习写法风格、知识点讲解方式和内容结构，不要复制内容或数据）
{ref_text}

## 历史表现分析（供参考风格方向）
{perf_text if perf_text else '暂无历史数据'}
{review_section}
## 写作要求
1. 标题：20字以内，数字冲击感+痛点/悬念（如"90%新手不懂的XX"）
2. 正文字数：最多600字！这是发布平台的硬性上限，超过就废稿。宁可少讲一个点，也绝不超600字。免责声明和标签不算在内。写完后自己数一遍
3. 开头3行抓人：痛点共鸣、反常识观点、或"你知道吗"式提问
4. 结构清晰：用 ## 小标题分段，**粗体**强调关键概念
5. 科普导向：把复杂概念讲得通俗易懂，多用比喻和假设场景，少用术语堆砌
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

    # ─── 字数检查 + 超限重试（最多重试1次） ───
    MAX_WORD_COUNT = 1000
    for attempt in range(2):
        title_match = re.search(r'^#\s+(.+)$', article, re.MULTILINE)
        if not title_match:
            log.warning("无法从生成内容中提取标题")
            return None

        # 计算正文字数（去掉 frontmatter、标题行、标签行、分隔线、免责声明）
        body = article
        body = re.sub(r'^---\n.*?\n---\n', '', body, count=1, flags=re.DOTALL)
        body = re.sub(r'^#\s+.+\n', '', body, count=1, flags=re.MULTILINE)
        body = re.sub(r'^\*标签：.+\*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^\*版本：.+\*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^---+$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^⚠️.*$', '', body, flags=re.MULTILINE)
        word_count = len(re.sub(r'\s+', '', body))

        if word_count <= MAX_WORD_COUNT:
            break

        if attempt == 0:
            log.warning("⚠️ 正文 %d 字超限，要求 Claude 精简...", word_count)
            trim_prompt = f"""以下文章正文有 {word_count} 字，超出了600字的硬性限制。
请精简到600字以内，保持原有格式（frontmatter + 标题 + 正文 + 免责 + 标签）不变。
删减内容时优先砍掉次要的例子和重复的解释，保留核心概念和结构。
直接输出精简后的完整文章，不要有任何额外说明。

{article}"""
            trimmed = call_claude(trim_prompt)
            if trimmed:
                article = trimmed
            else:
                log.warning("精简重试失败，使用原文")
                break
        else:
            log.warning("⚠️ 精简后仍有 %d 字，使用当前版本", word_count)

    raw_title = title_match.group(1).strip()
    word_count = word_count  # 使用循环最后计算的值

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
def main(force_count: int = None) -> None:
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
    if force_count:
        notes_needed = force_count
        log.info("强制生成 %d 篇（--count 参数）", notes_needed)
    else:
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
        all_keywords = theme.get("keywords", [])

        # 1. 多平台素材采集（小红书 + YouTube + Reddit + RSS + Web）
        log.info("多平台采集素材: %s（%d个关键词）", theme["name"], len(all_keywords))
        materials_by_source = collect_all(
            keywords=all_keywords,
            max_per_source=20,
        )
        ref_text = materials_to_prompt_text(materials_by_source, max_per_source=10)

        # 2. 生成文章
        article = generate_article(theme, ref_text,
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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=0,
                        help="强制生成指定篇数（忽略库存检查）")
    args = parser.parse_args()
    main(force_count=args.count if args.count > 0 else None)
