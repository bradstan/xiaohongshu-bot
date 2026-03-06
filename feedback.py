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
PUBLISHED_DIR = Path("/Users/jarvis/xiaohongshu-mcp/vault/已发布")
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


# ─── 逐篇复盘（写入文章自身页面顶部）─────────────────────────────────────────
REVIEW_MARKER = "<!-- 复盘数据 -->"
REVIEW_END    = "<!-- /复盘数据 -->"


def _build_article_review(entry: dict, now: datetime) -> str:
    """为单篇文章生成复盘区块（Markdown），将嵌入文章顶部"""
    cp = entry.get("checkpoints", {})
    title = entry.get("title", "?")
    pub_date = entry.get("published_at", "")[:16]

    rows = []
    for label in ["30分钟", "1小时", "3小时", "6小时", "24小时"]:
        if label in cp:
            d = cp[label]
            rows.append(
                f"| {label} | {d.get('liked',0)} | {d.get('collected',0)} "
                f"| {d.get('comment',0)} | {d.get('shared',0)} |"
            )
    if not rows:
        return ""

    table = (
        "| 时间点 | 点赞 | 收藏 | 评论 | 分享 |\n"
        "|--------|------|------|------|------|\n"
        + "\n".join(rows)
    )

    latest = {}
    for label in ["24小时", "6小时", "3小时", "1小时", "30分钟"]:
        if label in cp:
            latest = cp[label]
            break

    return f"""{REVIEW_MARKER}
> 📊 **互动数据** | 更新于 {now.strftime('%Y-%m-%d %H:%M')}

{table}

> **AI 复盘**：*(待分析...)*

{REVIEW_END}"""


def write_review_to_article(entry: dict, now: datetime) -> None:
    """将复盘区块写入文章页面顶部（frontmatter 之后、正文之前）"""
    md_path = Path(entry.get("file", ""))
    if not md_path.exists():
        return

    cp = entry.get("checkpoints", {})
    if not cp:
        return

    text = md_path.read_text(encoding="utf-8")
    review_block = _build_article_review(entry, now)
    if not review_block:
        return

    # 如果已有复盘区块，替换它（保留已有 AI 分析）
    if REVIEW_MARKER in text:
        old_match = re.search(
            rf'{re.escape(REVIEW_MARKER)}.*?{re.escape(REVIEW_END)}',
            text, re.DOTALL
        )
        if old_match:
            old_block = old_match.group()
            # 保留已有的 AI 复盘内容（非占位符）
            ai_match = re.search(r'> \*\*AI 复盘\*\*：(.*?)(?=\n\n<!--)', old_block, re.DOTALL)
            if ai_match and "*(待分析...)*" not in ai_match.group(1):
                existing_ai = ai_match.group(1).strip()
                review_block = review_block.replace("*(待分析...)*", existing_ai)
            text = text.replace(old_block, review_block)
    else:
        # 插入到 frontmatter 之后
        lines = text.split("\n")
        insert_idx = 0
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    insert_idx = i + 1
                    break
        # 跳过紧跟的空行
        while insert_idx < len(lines) and lines[insert_idx].strip() == "":
            insert_idx += 1
        lines.insert(insert_idx, review_block + "\n")
        text = "\n".join(lines)

    md_path.write_text(text, encoding="utf-8")
    log.info("复盘数据已写入: %s", md_path.name)


def generate_article_analysis(entry: dict) -> None:
    """为单篇文章生成 AI 复盘分析，替换页面中的占位符"""
    md_path = Path(entry.get("file", ""))
    if not md_path.exists():
        return

    text = md_path.read_text(encoding="utf-8")
    if "*(待分析...)*" not in text:
        return  # 已有分析或无占位符

    # 需要至少 6h 数据才生成分析
    cp = entry.get("checkpoints", {})
    if not any(label in cp for label in ["6小时", "24小时"]):
        return

    title = entry.get("title", "?")
    rows = []
    for label in ["30分钟", "1小时", "3小时", "6小时", "24小时"]:
        if label in cp:
            d = cp[label]
            rows.append(f"  {label}: 点赞{d.get('liked',0)} 收藏{d.get('collected',0)} "
                        f"评论{d.get('comment',0)} 分享{d.get('shared',0)}")

    prompt = f"""你是小红书运营分析师。针对这篇文章的表现数据，用2-3句话给出精炼的复盘总结。

标题：{title}
数据：
{chr(10).join(rows)}

要求：
- 用1-2句话点评数据表现（好/差在哪）
- 用1句话给出最关键的优化建议
- 总共不超过80字
- 直接输出文字，不要标题或格式"""

    log.info("为 [%s] 生成 AI 复盘...", title[:15])
    analysis = call_llm(prompt, max_tokens=200)
    if not analysis:
        return

    # 清理：取第一段，限制长度
    analysis = analysis.strip().split("\n\n")[0].strip()
    if len(analysis) > 150:
        analysis = analysis[:147] + "..."

    text = text.replace("*(待分析...)*", analysis, 1)
    md_path.write_text(text, encoding="utf-8")

    # 改 emoji：✅ → 📊
    new_name = md_path.name.replace("✅", "📊", 1)
    if new_name != md_path.name:
        new_path = md_path.parent / new_name
        md_path.rename(new_path)
        entry["file"] = str(new_path)
        log.info("复盘完成，已重命名: %s", new_name)


# ─── 主题权重更新 ─────────────────────────────────────────────────────────────
THEME_WEIGHTS_FILE = SCRIPT_DIR / "state" / "theme_weights.json"


def update_theme_weights(state: dict) -> None:
    """
    根据已发布文章的互动数据（最新 checkpoint）计算每个主题的综合得分，
    归一化后写入 state/theme_weights.json。
    research.py 的 pick_themes() 读取此文件打散同库存主题的顺序。

    得分公式：score = collected * 3 + liked * 1 + comment * 2 + shared * 2
    （收藏权重最高，因为代表内容质量；评论/分享代表传播力）
    """
    CHECKPOINT_ORDER = ["24小时", "6小时", "3小时", "1小时", "30分钟"]

    theme_scores: dict = {}   # theme_id -> list of scores
    for entry in state.get("published", []):
        tid = entry.get("theme_id", "unknown")
        if tid == "unknown":
            continue
        cp = entry.get("checkpoints", {})
        if not cp:
            continue
        # 取最新时间点数据
        latest = {}
        for label in CHECKPOINT_ORDER:
            if label in cp:
                latest = cp[label]
                break
        if not latest:
            continue
        score = (latest.get("collected", 0) * 3 +
                 latest.get("liked",     0) * 1 +
                 latest.get("comment",   0) * 2 +
                 latest.get("shared",    0) * 2)
        theme_scores.setdefault(tid, []).append(score)

    if not theme_scores:
        return

    # 每个主题取平均分
    avg_scores = {tid: sum(scores) / len(scores)
                  for tid, scores in theme_scores.items()}

    # 归一化到 [0.5, 2.0]（保证低分主题仍有机会被选到）
    max_s = max(avg_scores.values()) or 1.0
    weights = {tid: round(0.5 + (s / max_s) * 1.5, 3)
               for tid, s in avg_scores.items()}

    THEME_WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    THEME_WEIGHTS_FILE.write_text(
        json.dumps({"updated": datetime.now().strftime("%Y-%m-%d"),
                    "weights": weights}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("theme_weights.json 已更新：%s",
             " | ".join(f"{tid}={w}" for tid, w in sorted(weights.items(),
                                                           key=lambda x: -x[1])))


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

    # 逐篇写入复盘数据 + AI 分析
    review_changed = False
    for entry in state["published"]:
        cp = entry.get("checkpoints", {})
        if not cp:
            continue
        write_review_to_article(entry, now)
        old_file = entry.get("file", "")
        generate_article_analysis(entry)
        if entry.get("file", "") != old_file:
            review_changed = True  # AI 分析重命名了文件

    # 仅在 AI 分析重命名了文件时才需要再次保存
    if review_changed:
        save_state(state)
        log.info("文件重命名后状态已同步")

    # 更新主题权重（供 research.py pick_themes() 参考）
    update_theme_weights(state)

    log.info("=" * 50)


if __name__ == "__main__":
    main()
