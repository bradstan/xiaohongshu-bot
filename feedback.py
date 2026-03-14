#!/usr/bin/env python3
"""
互动数据反馈脚本
- 读取 published.json，找出需要拉取数据的时间点
- 调用 get_feed_detail 获取点赞/收藏/评论/分享数
- 回写到对应 Obsidian .md 文件末尾
- 检查时间点：发布后 30min / 1h / 3h / 6h / 24h
- 调用 Claude CLI 自动生成优化建议和写作方向
"""

import json
import os
import re
import sys
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import urllib.request
import urllib.error

# launchd 环境没有用户 PATH，确保 Homebrew 路径可用（node 等依赖）
if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

# ─── 配置 ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path("/Users/jarvis/xiaohongshu-mcp")
STATE_FILE  = SCRIPT_DIR / "published.json"
TOPICS_FILE = SCRIPT_DIR / "topics.json"
LOG_FILE    = SCRIPT_DIR / "feedback.log"
REVIEW_DIR  = Path("/Users/jarvis/xiaohongshu-mcp/vault/已发布/复盘")
MCP_URL     = "http://localhost:18060/mcp"
MCP_ACCEPT  = "application/json, text/event-stream"

CHECKPOINTS = [
    (30,   "30分钟"),
    (60,   "1小时"),
    (180,  "3小时"),
    (360,  "6小时"),
    (1440, "24小时"),
]

TRACKING_HEADER = "## 📊 发布数据追踪"

# ─── 日志（独立 logger，避免 launchd 重定向导致双重输出）────────────────────
log = logging.getLogger("feedback")
log.setLevel(logging.INFO)
if not log.handlers:
    _fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    log.addHandler(_fh)
    log.addHandler(_sh)


# ─── 状态管理 ─────────────────────────────────────────────────────────────────
def load_topics() -> dict:
    """加载 topics.json 配置"""
    if TOPICS_FILE.exists():
        with TOPICS_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def infer_theme_id(title: str, topics_config: dict) -> str:
    """根据标题关键词匹配 topics.json 中的 theme"""
    for theme in topics_config.get("themes", []):
        for kw in theme.get("keywords", []):
            if kw.lower() in title.lower():
                return theme["id"]
    return "unknown"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"published": []}
    with STATE_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)
    # 兼容旧格式（string 条目）+ 回填 theme_id
    topics_config = load_topics()
    entries = []
    for e in raw.get("published", []):
        if isinstance(e, str):
            entries.append({"file": e, "title": "", "published_at": "",
                            "feed_id": "", "xsec_token": "", "checkpoints": {},
                            "theme_id": "unknown"})
        else:
            if "checkpoints" not in e:
                e["checkpoints"] = {}
            # 回填缺失的 theme_id
            if "theme_id" not in e:
                e["theme_id"] = infer_theme_id(e.get("title", ""), topics_config)
            entries.append(e)
    raw["published"] = entries
    return raw


def save_state(state: dict) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── MCP 调用 ─────────────────────────────────────────────────────────────────
_session_id: Optional[str] = None


def ensure_mcp_running() -> None:
    """确保 MCP server 在运行（调用 start_mcp.sh）"""
    try:
        subprocess.run(
            ["/bin/bash", str(SCRIPT_DIR / "start_mcp.sh")],
            capture_output=True, timeout=30,
        )
    except Exception as e:
        log.warning("启动 MCP 失败: %s", e)


def get_session() -> str:
    global _session_id
    if _session_id:
        return _session_id
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "feedback", "version": "1.0"},
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
    payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}).encode()
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


# ─── 互动数据拉取 ─────────────────────────────────────────────────────────────
def fetch_stats(feed_id: str, xsec_token: str) -> Optional[dict]:
    """调用 get_feed_detail，返回互动数据 dict 或 None"""
    try:
        result = call_tool("get_feed_detail", {
            "feed_id": feed_id,
            "xsec_token": xsec_token,
        })
        if "error" in result:
            log.warning("get_feed_detail 错误: %s", result["error"])
            return None

        # 新版 MCP 直接返回结构化 JSON
        interact = (
            result.get("data", {}).get("note", {}).get("interactInfo") or
            result.get("data", {}).get("interactInfo") or
            {}
        )

        # 兜底：尝试从旧版文本格式解析
        if not interact:
            text = ""
            inner = result.get("result", {}).get("content", [])
            if inner:
                text = inner[0].get("text", "")
            try:
                data = json.loads(text)
            except Exception:
                data = {}
            interact = (
                data.get("interactInfo") or
                data.get("noteCard", {}).get("interactInfo") or
                data.get("note", {}).get("interactInfo") or
                data.get("data", {}).get("note", {}).get("interactInfo") or
                {}
            )

        def to_int(val) -> int:
            try:
                return int(str(val).replace(",", "").replace(".", ""))
            except Exception:
                return 0

        stats = {
            "liked":     to_int(interact.get("likedCount", 0)),
            "collected": to_int(interact.get("collectedCount", 0)),
            "comment":   to_int(interact.get("commentCount", 0)),
            "shared":    to_int(interact.get("sharedCount", 0)),
        }
        log.info("互动数据: 点赞%d 收藏%d 评论%d 分享%d",
                 stats["liked"], stats["collected"], stats["comment"], stats["shared"])
        return stats

    except Exception as e:
        log.warning("拉取互动数据失败: %s", e)
        return None


# ─── 写回 Obsidian ────────────────────────────────────────────────────────────
TABLE_HEADER = (
    "\n---\n"
    f"{TRACKING_HEADER}\n\n"
    "| 时间点 | 点赞 | 收藏 | 评论 | 分享 |\n"
    "|--------|------|------|------|------|\n"
)


def write_stats_to_md(md_path_str: str, label: str, stats: dict) -> None:
    """将互动数据追加/更新到 .md 文件的数据追踪表格"""
    md_path = Path(md_path_str)
    if not md_path.exists():
        log.warning("文件不存在，跳过: %s", md_path_str)
        return

    try:
        text = md_path.read_text(encoding="utf-8")
        new_row = f"| {label} | {stats['liked']} | {stats['collected']} | {stats['comment']} | {stats['shared']} |"

        if TRACKING_HEADER in text:
            if f"| {label} |" in text:
                text = re.sub(
                    rf'\| {re.escape(label)} \|[^\n]*',
                    new_row,
                    text,
                )
            else:
                lines = text.splitlines()
                insert_at = len(lines)
                in_table = False
                for i, line in enumerate(lines):
                    if TRACKING_HEADER in line:
                        in_table = True
                    if in_table and line.startswith("|"):
                        insert_at = i + 1
                lines.insert(insert_at, new_row)
                text = "\n".join(lines)
        else:
            text = text.rstrip() + TABLE_HEADER + new_row + "\n"

        md_path.write_text(text, encoding="utf-8")
        log.info("已写入 %s → %s", label, md_path.name)
    except PermissionError:
        log.warning("无文件写入权限（macOS TCC），跳过写 md: %s", md_path.name)
    except Exception as e:
        log.warning("写 md 文件失败: %s — %s", md_path.name, e)


# ─── 重试搜索 feed_id ─────────────────────────────────────────────────────────
def retry_find_feed_id(entry: dict) -> tuple[str, str]:
    """
    对 feed_id 为空的条目重新搜索。
    策略：1) 用标题前 10 字搜索  2) 用 list_feeds 从主页匹配
    """
    title = entry.get("title", "")
    if not title:
        return "", ""

    # ── 策略 1: 关键词搜索（用短标题避免截断不匹配）──
    try:
        short_keyword = title[:10]
        result = call_tool("search_feeds", {"keyword": short_keyword})
        text = ""
        inner = result.get("result", {}).get("content", [])
        if inner:
            text = inner[0].get("text", "")
        try:
            feeds_data = json.loads(text)
        except Exception:
            feeds_data = {}

        feeds = []
        if isinstance(feeds_data, dict):
            feeds = feeds_data.get("feeds", []) or feeds_data.get("items", [])

        clean_title = re.sub(r'\s+', '', title)
        for feed in feeds:
            note_card = feed.get("noteCard", {})
            display_title = re.sub(r'\s+', '', note_card.get("displayTitle", ""))
            if clean_title in display_title or display_title in clean_title:
                fid = feed.get("id", "")
                tok = feed.get("xsecToken", "")
                if fid:
                    log.info("搜索找到 feed_id: %s → %s", title[:15], fid)
                    return fid, tok
    except Exception as e:
        log.warning("搜索 feed_id 失败: %s", e)

    # ── 策略 2: 从用户主页 feeds 匹配 ──
    try:
        result = call_tool("list_feeds", {})
        text = ""
        inner = result.get("result", {}).get("content", [])
        if inner:
            text = inner[0].get("text", "")
        try:
            feeds_data = json.loads(text)
        except Exception:
            feeds_data = {}

        feeds = []
        if isinstance(feeds_data, dict):
            feeds = feeds_data.get("feeds", []) or feeds_data.get("items", [])
        elif isinstance(feeds_data, list):
            feeds = feeds_data

        clean_title = re.sub(r'\s+', '', title)
        for feed in feeds:
            note_card = feed.get("noteCard", {})
            display_title = re.sub(r'\s+', '', note_card.get("displayTitle", ""))
            if clean_title in display_title or display_title in clean_title:
                fid = feed.get("id", "")
                tok = feed.get("xsecToken", "")
                if fid:
                    log.info("主页匹配找到 feed_id: %s → %s", title[:15], fid)
                    return fid, tok
    except Exception as e:
        log.warning("主页匹配 feed_id 失败: %s", e)

    return "", ""


# ─── LLM 调用（统一模块） ────────────────────────────────────────────────────
from llm import call_llm


# ─── 复盘文件生成 ─────────────────────────────────────────────────────────────
def build_data_summary(entries: list) -> str:
    """将所有已发文章的 checkpoint 数据格式化为分析用文本"""
    sections = []
    for e in entries:
        cp = e.get("checkpoints", {})
        title = e.get("title", "?")
        theme = e.get("theme_id", "unknown")
        pub_date = e.get("published_at", "")[:16]

        rows = []
        for label in ["30分钟", "1小时", "3小时", "6小时", "24小时"]:
            if label in cp:
                d = cp[label]
                rows.append(f"  {label}: 点赞{d.get('liked',0)} 收藏{d.get('collected',0)} "
                            f"评论{d.get('comment',0)} 分享{d.get('shared',0)}")

        # 计算增长趋势
        early = cp.get("30分钟", {})
        latest = {}
        for label in ["24小时", "6小时", "3小时", "1小时"]:
            if label in cp:
                latest = cp[label]
                break
        growth = ""
        if early and latest:
            delta_c = latest.get("collected", 0) - early.get("collected", 0)
            delta_l = latest.get("liked", 0) - early.get("liked", 0)
            growth = f"  增长趋势: 收藏+{delta_c} 点赞+{delta_l}"

        section = f"📄 {title}\n  主题: {theme} | 发布: {pub_date}\n"
        section += "\n".join(rows)
        if growth:
            section += "\n" + growth
        sections.append(section)

    return "\n\n".join(sections)


def update_review(state: dict, now: datetime) -> Path:
    """根据 published.json 里的最新数据，自动生成/更新当周复盘文件"""
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end   = (now - timedelta(days=now.weekday()) + timedelta(days=6)).strftime("%Y-%m-%d")
    review_file = REVIEW_DIR / f"{now.strftime('%Y-%m-%d')}｜已发内容复盘.md"

    entries = [
        e for e in state["published"]
        if e.get("published_at") and e.get("checkpoints")
    ]

    if not entries:
        return review_file

    # ── 汇总数据表 ──
    summary_rows = []
    for e in entries:
        cp = e.get("checkpoints", {})
        latest = {}
        for label in ["24小时", "6小时", "3小时", "1小时", "30分钟"]:
            if label in cp:
                latest = cp[label]
                break
        title_short = e.get("title", "?")[:20]
        pub_date = e.get("published_at", "")[:10]
        theme = e.get("theme_id", "?")
        liked     = latest.get("liked", "-")
        collected = latest.get("collected", "-")
        comment   = latest.get("comment", "-")
        summary_rows.append(
            f"| {pub_date} | {title_short} | {theme} | {liked} | {collected} | {comment} |"
        )

    summary_table = (
        "| 发布日期 | 标题 | 主题 | 点赞 | 收藏 | 评论 |\n"
        "|----------|------|------|------|------|------|\n"
        + "\n".join(summary_rows)
    )

    # ── 各文章详细趋势 ──
    detail_sections = []
    for e in entries:
        cp = e.get("checkpoints", {})
        title = e.get("title", "?")
        pub_date = e.get("published_at", "")[:10]
        rows = []
        for label in ["30分钟", "1小时", "3小时", "6小时", "24小时"]:
            if label in cp:
                d = cp[label]
                rows.append(
                    f"| {label} | {d.get('liked',0)} | {d.get('collected',0)} | {d.get('comment',0)} | {d.get('shared',0)} |"
                )
        if not rows:
            continue
        table = (
            "| 时间点 | 点赞 | 收藏 | 评论 | 分享 |\n"
            "|--------|------|------|------|------|\n"
            + "\n".join(rows)
        )
        detail_sections.append(f"### 📄 {title}\n\n> 发布时间：{pub_date}\n\n{table}")

    detail_str = "\n\n".join(detail_sections)

    # ── 组装复盘文件 ──
    # 如果文件已存在且含 AI 分析，保留三、四部分
    ai_section = """## 三、优化建议

> *(待AI分析...)*

---

## 四、下一篇写作方向

> *(待AI分析...)*"""

    if review_file.exists():
        old_text = review_file.read_text(encoding="utf-8")
        # 提取已有的 AI 分析内容（从 ## 三 到 自动生成之前）
        m = re.search(r'(## 三、优化建议.*?)(?=\n---\n\n\*自动生成)', old_text, re.DOTALL)
        if m and "*(待AI分析...)*" not in m.group(1):
            ai_section = m.group(1).rstrip()
            log.info("保留已有 AI 分析内容")

    content = f"""# {now.strftime('%Y-%m-%d')}｜已发内容复盘

> 统计周期：{week_start} ~ {week_end}
> 最后更新：{now.strftime('%Y-%m-%d %H:%M')}

---

## 一、数据概况

共发布 **{len(entries)}** 篇内容。

{summary_table}

---

## 二、各文章互动趋势

{detail_str}

---

{ai_section}

---

*自动生成 @ {now.strftime('%Y-%m-%d %H:%M')}*
"""

    review_file.write_text(content, encoding="utf-8")
    log.info("复盘文件已更新: %s", review_file.name)
    return review_file


# ─── AI 自动分析 ──────────────────────────────────────────────────────────────
def generate_analysis(state: dict, review_file: Path, now: datetime) -> None:
    """
    调用 Claude CLI 生成优化建议和写作方向，替换复盘文件中的占位符。
    频率控制：每天最多生成一次（通过检查文件内容判断）。
    前置条件：至少有 1 篇文章有 6h+ checkpoint 数据。
    """
    if not review_file.exists():
        return

    text = review_file.read_text(encoding="utf-8")

    # 如果已经有 AI 分析内容（不是占位符），跳过
    if "*(待AI分析...)*" not in text:
        log.info("复盘文件已有分析内容，跳过 AI 生成")
        return

    # 检查是否有足够数据
    entries_with_data = [
        e for e in state["published"]
        if any(label in e.get("checkpoints", {})
               for label in ["6小时", "24小时"])
    ]
    if not entries_with_data:
        log.info("暂无足够 checkpoint 数据（需 6h+），跳过 AI 分析")
        return

    # 构建分析 prompt
    data_summary = build_data_summary(
        [e for e in state["published"] if e.get("checkpoints")]
    )

    prompt = f"""你是小红书运营数据分析师。根据以下已发布内容的互动数据，生成分析和优化建议。

## 已发布内容数据

{data_summary}

## 分析要求

请生成以下两个章节的完整 Markdown 内容：

### 三、优化建议

分析每篇文章的表现，给出具体可执行的优化建议：
1. **标题优化**（2条）：针对表现差的文章，给出标题改写建议（原文 → 优化后）
2. **开头3行优化**（2条）：给出更抓人的开头写法
3. **结构优化**（2条）：内容结构如何改进（如加行动清单、反面案例等）
4. **互动引导优化**：如何提高评论率

### 四、下一篇写作方向

基于数据分析，给出具体的下一篇写作指令：
- 推荐主题和标题（2-3个备选）
- 为什么选这个方向（数据依据）
- 内容结构建议
- 标签建议

注意：
- 我们是**期权知识科普**账号，不写真实市场数据，用假设场景举例
- 收藏率高 = 干货属性强，应多出这类内容
- 评论数 = 互动性强，需加强互动引导

请直接输出 Markdown 格式内容，不要有前后说明文字。"""

    log.info("调用 Claude 生成分析报告...")
    analysis = call_llm(prompt)
    if not analysis:
        log.warning("AI 分析生成失败")
        return

    # 替换占位符
    text = text.replace(
        "## 三、优化建议\n\n> *(待AI分析...)*\n\n---\n\n## 四、下一篇写作方向\n\n> *(待AI分析...)*",
        analysis
    )

    review_file.write_text(text, encoding="utf-8")
    log.info("AI 分析已写入复盘文件")


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=" * 50)
    log.info("互动数据检查 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # 确保 MCP server 在运行
    ensure_mcp_running()

    if not check_mcp_alive():
        log.error("MCP server 不可达，跳过")
        return

    state = load_state()
    now = datetime.now()
    changed = False

    for entry in state["published"]:
        if not entry.get("published_at"):
            continue

        try:
            pub_time = datetime.fromisoformat(entry["published_at"])
        except Exception:
            continue

        elapsed_minutes = (now - pub_time).total_seconds() / 60

        # 如果 feed_id 为空，尝试重新搜索（48h 内重试）
        if not entry.get("feed_id") and elapsed_minutes < 2880:
            fid, tok = retry_find_feed_id(entry)
            if fid:
                entry["feed_id"] = fid
                entry["xsec_token"] = tok
                changed = True

        if not entry.get("feed_id"):
            continue

        feed_id    = entry["feed_id"]
        xsec_token = entry["xsec_token"]
        checkpoints_done = entry.get("checkpoints", {})

        for minutes, label in CHECKPOINTS:
            if label in checkpoints_done:
                continue
            if elapsed_minutes < minutes:
                continue

            log.info("拉取 [%s] %s 数据...", entry.get("title", "?"), label)
            stats = fetch_stats(feed_id, xsec_token)
            if stats is not None:
                write_stats_to_md(entry["file"], label, stats)
                entry["checkpoints"][label] = {
                    **stats,
                    "fetched_at": now.isoformat(timespec="seconds"),
                }
                changed = True

    if changed:
        save_state(state)
        log.info("状态已保存")
    else:
        log.info("无需更新")

    # 更新复盘文件 + AI 分析
    review_file = update_review(state, now)
    generate_analysis(state, review_file, now)


if __name__ == "__main__":
    main()
