#!/usr/bin/env python3
"""
选题策划脚本
- 读取 topics.json 获取主题方向
- 搜索小红书各主题的热门内容
- 读取复盘数据分析哪类话题表现好
- 输出本周选题+写作指令 → 待策划/YYYY-MM-DD｜本周选题策划.md
"""

import json
import re
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error

# ─── 配置 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path("/Users/jarvis/xiaohongshu-mcp")
TOPICS_FILE  = SCRIPT_DIR / "topics.json"
STATE_FILE   = SCRIPT_DIR / "published.json"
LOG_FILE     = SCRIPT_DIR / "research.log"
PLAN_DIR     = Path("/Users/jarvis/Documents/小红书/待策划")
REVIEW_DIR   = Path("/Users/jarvis/Documents/小红书/已发布/复盘")
MCP_URL      = "http://localhost:18060/mcp"
MCP_ACCEPT   = "application/json, text/event-stream"

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


# ─── 复盘数据分析 ─────────────────────────────────────────────────────────────
def analyze_past_performance(state: dict) -> dict:
    """分析已发文章的表现，返回各主题的平均收藏/点赞数"""
    performance = {}
    for entry in state.get("published", []):
        cp = entry.get("checkpoints", {})
        # 取 24小时 数据，没有就取最新
        data = {}
        for label in ["24小时", "6小时", "3小时", "1小时", "30分钟"]:
            if label in cp:
                data = cp[label]
                break
        if not data:
            continue
        title = entry.get("title", "")
        collected = data.get("collected", 0)
        liked = data.get("liked", 0)
        performance[title] = {"collected": collected, "liked": liked}

    return performance


def get_top_performers(performance: dict, n: int = 3) -> list:
    """返回收藏数最高的 n 篇文章"""
    sorted_items = sorted(performance.items(), key=lambda x: x[1]["collected"], reverse=True)
    return sorted_items[:n]


# ─── 小红书搜索 ───────────────────────────────────────────────────────────────
def search_topic(keyword: str) -> list:
    """搜索关键词，返回热门笔记列表"""
    try:
        result = call_tool("search_feeds", {
            "keyword": keyword,
            "filters": {"sort_by": "最多收藏"}
        })
        # MCP 返回结构：result["result"]["content"][0]["text"] 是 JSON 字符串
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
        for feed in feeds[:5]:  # 只取前5条
            note_card = feed.get("noteCard", {})
            title = note_card.get("displayTitle", "") or note_card.get("title", "")
            interact = note_card.get("interactInfo", {})
            collected = interact.get("collectedCount", "0")
            liked = interact.get("likedCount", "0")
            if title:
                notes.append({
                    "title": title,
                    "collected": collected,
                    "liked": liked,
                })
        return notes
    except Exception as e:
        log.warning("搜索 [%s] 失败: %s", keyword, e)
        return []


# ─── 选题生成 ─────────────────────────────────────────────────────────────────
def build_plan(topics_config: dict, search_results: dict, performance: dict, now: datetime) -> str:
    """组装选题策划 Markdown 文件内容"""

    account_desc = topics_config.get("account_description", "")
    target_audience = topics_config.get("target_audience", "")
    content_style = topics_config.get("content_style", "")
    notes_per_plan = topics_config.get("notes_per_plan", 5)

    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end   = (now - timedelta(days=now.weekday()) + timedelta(days=6)).strftime("%Y-%m-%d")

    # ── 数据表现回顾 ──
    top_performers = get_top_performers(performance)
    if top_performers:
        perf_rows = "\n".join(
            f"| {title[:22]} | {d['collected']} | {d['liked']} |"
            for title, d in top_performers
        )
        perf_section = (
            "## 📈 历史数据参考（收藏最高）\n\n"
            "| 文章标题 | 收藏 | 点赞 |\n"
            "|----------|------|------|\n"
            f"{perf_rows}\n\n"
            "> 选题时优先参考收藏数高的方向，说明读者有保存意愿（干货感强）\n"
        )
    else:
        perf_section = "## 📈 历史数据参考\n\n> 暂无足够数据，本周以探索为主\n"

    # ── 热门内容参考 ──
    hot_sections = []
    for theme in topics_config.get("themes", []):
        theme_name = theme["name"]
        keyword = theme["keywords"][0]
        notes = search_results.get(keyword, [])
        if not notes:
            continue
        rows = "\n".join(
            f"| {n['title'][:25]} | {n['collected']} | {n['liked']} |"
            for n in notes
        )
        hot_sections.append(
            f"### {theme_name}（搜索词：{keyword}）\n\n"
            "| 热门标题 | 收藏 | 点赞 |\n"
            "|----------|------|------|\n"
            f"{rows}"
        )
    hot_content = "\n\n".join(hot_sections)

    # ── 选题列表（每个主题出1题，共 notes_per_plan 题）──
    themes = topics_config.get("themes", [])
    plan_items = []
    for i, theme in enumerate(themes[:notes_per_plan], 1):
        theme_name = theme["name"]
        keyword = theme["keywords"][0]
        hot = search_results.get(keyword, [])
        hot_ref = f"「{hot[0]['title'][:20]}」（收藏{hot[0]['collected']}）" if hot else "暂无参考"

        plan_items.append(f"""### 选题 {i}：{theme_name}

**参考热门**：{hot_ref}

**标题方向**（选一个或自拟）：
- *(根据热门内容和账号风格填写)*

**写作要求**：
1. **开头**：数字或痛点 hook，前3行抓住读者
2. **结构**：实战案例优先，数据/截图增强可信度
3. **互动**：文末引导评论（问一个具体问题）
4. **字数**：800-1000字（小红书正文限制1000字）
5. **标签**：8-10个，含大标签+细分标签

**账号定位参考**：
- 受众：{target_audience}
- 风格：{content_style}

---
""")

    plan_content = "\n".join(plan_items)

    return f"""# {now.strftime('%Y-%m-%d')}｜本周选题策划

> 策划周期：{week_start} ~ {week_end}
> 生成时间：{now.strftime('%Y-%m-%d %H:%M')}
> 目标篇数：{notes_per_plan} 篇

---

{perf_section}

---

## 🔥 小红书热门内容参考

{hot_content}

---

## 📝 本周选题

{plan_content}

---

## 使用说明

1. 从上方选题中选一个，填写标题方向
2. 在 Claude 里粘贴写作要求，执行写作
3. 写完后将文章放入 `待发布/` 文件夹
4. Pipeline 会在定时任务触发时自动发布

*自动生成 @ {now.strftime('%Y-%m-%d %H:%M')}*
"""


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=" * 50)
    log.info("选题策划 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not check_mcp_alive():
        log.error("MCP server 不可达，退出")
        return

    now = datetime.now()
    topics_config = load_topics()
    state = load_state()

    # 分析历史表现
    performance = analyze_past_performance(state)
    log.info("已分析 %d 篇历史文章", len(performance))

    # 搜索各主题热门内容
    search_results = {}
    themes = topics_config.get("themes", [])
    for theme in themes:
        keyword = theme["keywords"][0]
        log.info("搜索主题: %s（关键词: %s）", theme["name"], keyword)
        notes = search_topic(keyword)
        search_results[keyword] = notes
        log.info("  找到 %d 条热门内容", len(notes))

    # 生成策划文件
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    plan_content = build_plan(topics_config, search_results, performance, now)
    plan_file = PLAN_DIR / f"{now.strftime('%Y-%m-%d')}｜本周选题策划.md"
    plan_file.write_text(plan_content, encoding="utf-8")
    log.info("策划文件已生成: %s", plan_file.name)


if __name__ == "__main__":
    main()
