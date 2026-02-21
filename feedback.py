#!/usr/bin/env python3
"""
互动数据反馈脚本
- 读取 published.json，找出需要拉取数据的时间点
- 调用 get_feed_detail 获取点赞/收藏/评论/分享数
- 回写到对应 Obsidian .md 文件末尾
- 检查时间点：发布后 30min / 1h / 3h / 6h / 24h
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

# ─── 配置 ────────────────────────────────────────────────────────────────────
STATE_FILE = Path("/Users/jarvis/xiaohongshu-mcp/published.json")
LOG_FILE   = Path("/Users/jarvis/xiaohongshu-mcp/feedback.log")
MCP_URL    = "http://localhost:18060/mcp"
MCP_ACCEPT = "application/json, text/event-stream"

CHECKPOINTS = [
    (30,   "30分钟"),
    (60,   "1小时"),
    (180,  "3小时"),
    (360,  "6小时"),
    (1440, "24小时"),
]

TRACKING_HEADER = "## 📊 发布数据追踪"

# ─── 日志 ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ─── 状态管理 ─────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"published": []}
    with STATE_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)
    # 兼容旧格式（string 条目）
    entries = []
    for e in raw.get("published", []):
        if isinstance(e, str):
            entries.append({"file": e, "title": "", "published_at": "",
                            "feed_id": "", "xsec_token": "", "checkpoints": {}})
        else:
            if "checkpoints" not in e:
                e["checkpoints"] = {}
            entries.append(e)
    raw["published"] = entries
    return raw


def save_state(state: dict) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


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

        # 新版 MCP 直接返回结构化 JSON，路径：result["data"]["note"]["interactInfo"]
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

        # 有时 likedCount 是字符串数字
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

    text = md_path.read_text(encoding="utf-8")
    new_row = f"| {label} | {stats['liked']} | {stats['collected']} | {stats['comment']} | {stats['shared']} |"

    if TRACKING_HEADER in text:
        # 已有表格：检查该时间点行是否已存在
        if f"| {label} |" in text:
            # 更新已有行
            text = re.sub(
                rf'\| {re.escape(label)} \|[^\n]*',
                new_row,
                text,
            )
        else:
            # 在最后一个表格行后追加
            # 找表格末尾（最后一个 | 开头的行后面插入）
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
        # 没有表格：追加到文件末尾
        text = text.rstrip() + TABLE_HEADER + new_row + "\n"

    md_path.write_text(text, encoding="utf-8")
    log.info("已写入 %s → %s", label, md_path.name)


# ─── 重试搜索 feed_id ─────────────────────────────────────────────────────────
def retry_find_feed_id(entry: dict) -> tuple[str, str]:
    """对 feed_id 为空的条目重新搜索"""
    title = entry.get("title", "")
    if not title:
        return "", ""
    try:
        result = call_tool("search_feeds", {"keyword": title})
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
            display_title = note_card.get("displayTitle", "")
            if clean_title in re.sub(r'\s+', '', display_title) or \
               re.sub(r'\s+', '', display_title) in clean_title:
                fid = feed.get("id", "")
                tok = feed.get("xsecToken", "")
                if fid:
                    log.info("重试找到 feed_id: %s → %s", title, fid)
                    return fid, tok
    except Exception as e:
        log.warning("重试搜索 feed_id 失败: %s", e)
    return "", ""


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=" * 50)
    log.info("互动数据检查 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not check_mcp_alive():
        log.error("MCP server 不可达，跳过")
        return

    state = load_state()
    now = datetime.now()
    changed = False

    for entry in state["published"]:
        if not entry.get("published_at"):
            continue  # 旧格式没有时间戳，跳过

        try:
            pub_time = datetime.fromisoformat(entry["published_at"])
        except Exception:
            continue

        elapsed_minutes = (now - pub_time).total_seconds() / 60

        # 如果 feed_id 为空，尝试重新搜索（最多在 24h 内重试）
        if not entry.get("feed_id") and elapsed_minutes < 1500:
            fid, tok = retry_find_feed_id(entry)
            if fid:
                entry["feed_id"] = fid
                entry["xsec_token"] = tok
                changed = True

        if not entry.get("feed_id"):
            continue  # 还没找到 feed_id，跳过

        feed_id    = entry["feed_id"]
        xsec_token = entry["xsec_token"]
        checkpoints_done = entry.get("checkpoints", {})

        for minutes, label in CHECKPOINTS:
            if label in checkpoints_done:
                continue  # 已拉过
            if elapsed_minutes < minutes:
                continue  # 时间还没到

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


if __name__ == "__main__":
    main()
