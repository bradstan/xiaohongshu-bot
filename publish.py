#!/usr/bin/env python3
"""
小红书定时发布脚本
- 从 Obsidian Vault 读取 Markdown 文章
- 追踪已发布状态（published.json）
- 调用 xiaohongshu-mcp HTTP API 发布
- 发布后搜索 feed_id 供后续互动数据拉取
"""

import json
import re
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import urllib.request
import urllib.error

# 封面图生成
sys.path.insert(0, str(Path(__file__).parent))
from make_cover import generate_cover
from mark_published import mark_file

# ─── 配置 ────────────────────────────────────────────────────────────────────
VAULT_DIR  = Path("/Users/jarvis/Documents/Obsidian Vault/待发布")
STATE_FILE = Path("/Users/jarvis/xiaohongshu-mcp/published.json")
LOG_FILE   = Path("/Users/jarvis/xiaohongshu-mcp/publish.log")
MCP_URL    = "http://localhost:18060/mcp"
MCP_ACCEPT = "application/json, text/event-stream"

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
def _migrate_entry(entry) -> dict:
    """将旧格式（字符串路径）迁移为新格式（dict）"""
    if isinstance(entry, str):
        return {
            "file": entry,
            "title": "",
            "published_at": "",
            "feed_id": "",
            "xsec_token": "",
            "checkpoints": {},
        }
    return entry


def load_state() -> dict:
    if STATE_FILE.exists():
        with STATE_FILE.open(encoding="utf-8") as f:
            raw = json.load(f)
        # 迁移旧格式
        raw["published"] = [_migrate_entry(e) for e in raw.get("published", [])]
        return raw
    return {"published": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── 文章解析 ─────────────────────────────────────────────────────────────────
def parse_article(path: Path) -> dict:
    """
    从 Markdown 文件提取标题、正文、tags。
    支持两种格式：
    - 新格式：YAML frontmatter + H1 标题 + 正文
    - 旧格式：# 小红书笔记 v1.0 + ## 章节标题 + 正文
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # ── 1. 解析 YAML frontmatter ────────────────────────────────────────────
    tags: list[str] = []
    body_start = 0  # 正文从哪一行开始

    if lines and lines[0].strip() == "---":
        # 找结束的 ---
        end_fm = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_fm = i
                break
        if end_fm != -1:
            fm_text = "\n".join(lines[1:end_fm])
            # 提取 tags: [tag1, tag2, ...]
            tags_match = re.search(r'^tags:\s*\[([^\]]+)\]', fm_text, re.MULTILINE)
            if tags_match:
                tags = [t.strip() for t in tags_match.group(1).split(",") if t.strip()]
            body_start = end_fm + 1

    # ── 2. 提取标题（第一个 H1，去掉「已发」前缀）─────────────────────────
    title = ""
    h1_line_idx = -1
    for i in range(body_start, len(lines)):
        line = lines[i]
        if re.match(r'^# ', line):
            raw = line[2:].strip()
            # 去掉「（已发）」前缀
            raw = re.sub(r'^（已发）\s*', '', raw)
            # 去掉 Markdown 粗体标记和 emoji 前缀
            raw = re.sub(r'\*+', '', raw).strip()
            if raw:
                title = raw
                h1_line_idx = i
                break

    # 旧格式兜底：用第一个 ## 笔记N：... 的内容
    if not title:
        m = re.search(r'^##\s+(?:笔记\d+[：:]\s*)?(.+)$', text, re.MULTILINE)
        title = m.group(1).strip() if m else path.stem

    # 小红书标题限制 20 字
    if len(title) > 20:
        title = title[:20]

    # ── 3. 提取正文（H1 之后，跳过数据追踪章节）──────────────────────────
    content_start = (h1_line_idx + 1) if h1_line_idx != -1 else body_start
    body_lines = []
    for line in lines[content_start:]:
        if line.strip() == "## 📊 发布数据追踪":
            break
        body_lines.append(line)

    content = "\n".join(body_lines).strip()

    # 如果 tags 未从 frontmatter 提取，尝试从正文末尾的 #tag 提取
    if not tags:
        tags = re.findall(r'#([\w\u4e00-\u9fff]+)', content)

    # 去掉正文末尾的 hashtag 行（避免发布到小红书正文里）
    content_no_tags = re.sub(r'\n+#[\w\u4e00-\u9fff#\s]+$', '', content).strip()
    if len(content_no_tags) > 1000:
        content_no_tags = content_no_tags[:997] + "..."

    return {
        "title": title,
        "content": content_no_tags,
        "full_content": content,
        "tags": list(dict.fromkeys(tags)),
        "file": str(path),
    }


def get_pending_articles(state: dict) -> list[Path]:
    """返回尚未发布的文章，按文件名排序"""
    published_files = {e["file"] for e in state["published"]}
    all_md = sorted(VAULT_DIR.glob("*.md"))
    return [p for p in all_md if str(p) not in published_files]


# ─── MCP 调用 ─────────────────────────────────────────────────────────────────
_session_id: Optional[str] = None


def get_session() -> str:
    global _session_id
    if _session_id:
        return _session_id
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "publisher", "version": "1.0"},
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
    with urllib.request.urlopen(req, timeout=90) as resp:
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


# ─── 发布后搜索 feed_id ────────────────────────────────────────────────────────
def find_feed_id(title: str) -> tuple[str, str]:
    """
    发布成功后搜索自己的文章，获取 feed_id 和 xsec_token。
    返回 (feed_id, xsec_token)，失败返回 ("", "")
    """
    try:
        result = call_tool("search_feeds", {
            "keyword": title,
            "filters": {"search_scope": "已关注"}  # 搜自己发的
        })
        text = ""
        if "result" in result:
            inner = result["result"].get("content", [])
            if inner:
                text = inner[0].get("text", "")

        # 解析 JSON（search_feeds 返回 JSON 字符串）
        try:
            feeds_data = json.loads(text)
        except Exception:
            # 有时候直接是 dict
            feeds_data = result.get("result", {})

        feeds = []
        if isinstance(feeds_data, dict):
            feeds = feeds_data.get("feeds", []) or feeds_data.get("items", [])
        elif isinstance(feeds_data, list):
            feeds = feeds_data

        # 找最匹配标题的一条
        clean_title = re.sub(r'\s+', '', title)
        for feed in feeds:
            note_card = feed.get("noteCard", {})
            display_title = note_card.get("displayTitle", "")
            if clean_title in re.sub(r'\s+', '', display_title) or \
               re.sub(r'\s+', '', display_title) in clean_title:
                feed_id = feed.get("id", "")
                xsec_token = feed.get("xsecToken", "")
                if feed_id:
                    log.info("找到 feed_id: %s", feed_id)
                    return feed_id, xsec_token

        log.warning("未找到匹配的 feed，标题: %s", title)
        return "", ""
    except Exception as e:
        log.warning("搜索 feed_id 失败: %s", e)
        return "", ""


# ─── 发布文章 ─────────────────────────────────────────────────────────────────
def publish_article(article: dict, index: int = 0) -> bool:
    try:
        # 生成封面图（传入 full_content 用于提取要点）
        cover_path = generate_cover(
            article["title"],
            content=article.get("full_content", article["content"]),
            index=index,
        )
        log.info("封面图: %s", cover_path)

        args = {
            "title": article["title"],
            "content": article["content"],
            "images": [cover_path],
        }
        if article.get("tags"):
            args["tags"] = article["tags"][:10]  # 最多10个

        result = call_tool("publish_content", args)
        log.info("publish_content 响应: %s", json.dumps(result, ensure_ascii=False))

        if "error" in result:
            log.error("发布失败: %s", result["error"])
            return False

        res_content = result.get("result", {})
        if isinstance(res_content, dict):
            inner = res_content.get("content", [])
            if isinstance(inner, list) and inner:
                text = inner[0].get("text", "")
                if "error" in text.lower() and "成功" not in text:
                    log.error("发布可能失败: %s", text[:200])
                    return False
        return True

    except Exception as e:
        log.error("调用 MCP 工具异常: %s", e)
        return False


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=" * 60)
    log.info("定时发布任务启动 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not check_mcp_alive():
        log.error("MCP server 未运行，请先启动: ~/xiaohongshu-mcp/xiaohongshu-mcp-darwin-arm64")
        sys.exit(1)
    log.info("MCP server 连接正常")

    state = load_state()
    pending = get_pending_articles(state)

    if not pending:
        log.info("所有文章已发布完毕，无待发布内容")
        return

    target = pending[0]
    log.info("准备发布: %s", target.name)

    article = parse_article(target)
    log.info("标题: %s", article["title"])
    log.info("tags: %s", article["tags"])
    log.info("正文长度: %d 字符", len(article["content"]))

    published_count = len(state["published"])
    success = publish_article(article, index=published_count)

    if success:
        # 等待一下再搜索（让小红书索引生效）
        import time
        time.sleep(8)
        feed_id, xsec_token = find_feed_id(article["title"])

        entry = {
            "file": str(target),
            "title": article["title"],
            "published_at": datetime.now().isoformat(timespec="seconds"),
            "feed_id": feed_id,
            "xsec_token": xsec_token,
            "checkpoints": {},
        }
        state["published"].append(entry)
        save_state(state)

        # 移动文件到「已发布」文件夹
        published_dir = Path("/Users/jarvis/Documents/Obsidian Vault/已发布")
        published_dir.mkdir(parents=True, exist_ok=True)
        dest = published_dir / target.name
        target.rename(dest)
        marked_dest = mark_file(str(dest))
        entry["file"] = marked_dest
        state["published"][-1] = entry
        save_state(state)
        log.info("✓ 文件已移动并重命名: %s", Path(marked_dest).name)
        log.info("  feed_id: %s", feed_id or "（未找到，稍后 feedback.py 可重试）")
        log.info("已发布 %d 篇，剩余 %d 篇", len(state["published"]), len(pending) - 1)
    else:
        log.error("✗ 发布失败: %s", target.name)
        sys.exit(1)


if __name__ == "__main__":
    main()
