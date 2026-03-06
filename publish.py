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
SCRIPT_DIR = Path("/Users/jarvis/xiaohongshu-mcp")
VAULT_DIR  = Path("/Users/jarvis/xiaohongshu-mcp/vault/待发布")
STATE_FILE = SCRIPT_DIR / "published.json"
TOPICS_FILE = SCRIPT_DIR / "topics.json"
LOG_FILE   = SCRIPT_DIR / "publish.log"
MCP_URL    = "http://localhost:18060/mcp"
MCP_ACCEPT = "application/json, text/event-stream"

# ─── 日志 ────────────────────────────────────────────────────────────────────
log = logging.getLogger("publish")
log.setLevel(logging.INFO)
log.propagate = False
if not log.handlers:
    _fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    log.addHandler(_fh)
    log.addHandler(_sh)


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
    theme_id = ""
    category = ""
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
            # 提取 theme_id 和 category（用于精准发布统计）
            tm = re.search(r'^theme_id:\s*(\S+)', fm_text, re.MULTILINE)
            if tm:
                theme_id = tm.group(1).strip()
            cm = re.search(r'^category:\s*(\S+)', fm_text, re.MULTILINE)
            if cm:
                category = cm.group(1).strip()
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

    # 去掉正文末尾的元数据（标签行、版本行、hashtag 行）
    # 匹配：*标签：#xxx*、*版本：v1.0*、裸 #tag 行、⚠️免责声明、尾部 ---
    content_no_tags = re.sub(
        r'[\n\s]*(?:\*?标签[：:].*|\*?版本[：:].*|\*?[Vv]ersion[：:].*'
        r'|#[\w\u4e00-\u9fff#\s]+)\s*$',
        '', content, flags=re.DOTALL
    ).strip()
    # 去掉尾部残留的 --- 分隔线和免责声明
    content_no_tags = re.sub(
        r'[\n\s]*---[\n\s]*(?:⚠️.*)?[\n\s]*(?:---[\n\s]*)?$',
        '', content_no_tags
    ).strip()
    if len(content_no_tags) > 1000:
        content_no_tags = content_no_tags[:997] + "..."

    return {
        "title": title,
        "content": content_no_tags,
        "full_content": content,
        "tags": list(dict.fromkeys(tags)),
        "file": str(path),
        "theme_id": theme_id,
        "category": category,
    }


def get_article_category(path: Path) -> str:
    """从文章 frontmatter 中读取 category（不全文解析，快速读取）"""
    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r'^category:\s*(\S+)', text, re.MULTILINE)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def get_today_published_categories(state: dict) -> list[str]:
    """获取今日已发布文章的 category 列表（按发布时间顺序）"""
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        e.get("category", "")
        for e in state.get("published", [])
        if e.get("published_at", "").startswith(today)
    ]


def get_pending_articles(state: dict) -> list[Path]:
    """返回尚未发布的文章，按文件名排序"""
    published_files = {e["file"] for e in state["published"]}
    all_md = sorted(VAULT_DIR.glob("*.md"))
    # macOS TCC 可能让 glob 在 launchd/cron 下静默返回空，用 os.listdir 兜底
    if not all_md and VAULT_DIR.exists():
        import os
        try:
            all_md = sorted(
                VAULT_DIR / f for f in os.listdir(str(VAULT_DIR)) if f.endswith(".md")
            )
            if all_md:
                log.warning("glob 返回空但 os.listdir 找到 %d 个文件（疑似 TCC 权限问题）", len(all_md))
        except Exception as e:
            log.warning("os.listdir 也失败: %s", e)
    log.info("待发布目录: %s (exists=%s)", VAULT_DIR, VAULT_DIR.exists())
    log.info("找到 %d 个 md 文件, 已发布 %d 篇", len(all_md), len(published_files))
    pending = [p for p in all_md if str(p) not in published_files]
    if not pending and all_md:
        log.info("所有文件均已在 published.json 中")
    elif not all_md:
        log.info("待发布目录为空")
    return pending


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
MY_USER_ID = "54808b57d6e4a9616b300900"


def _parse_feeds_response(result: dict) -> list:
    """从 MCP 响应中解析 feeds 列表"""
    text = ""
    inner = result.get("result", {}).get("content", [])
    if inner:
        text = inner[0].get("text", "")
    try:
        feeds_data = json.loads(text)
    except Exception:
        feeds_data = result.get("result", {})
    if isinstance(feeds_data, dict):
        return feeds_data.get("feeds", []) or feeds_data.get("items", [])
    elif isinstance(feeds_data, list):
        return feeds_data
    return []


def _match_feed(feeds: list, title: str) -> tuple[str, str]:
    """从 feeds 列表中匹配标题，优先匹配自己的笔记"""
    clean_title = re.sub(r'\s+', '', title)
    # 第一轮：标题匹配 + 是自己发的
    for feed in feeds:
        nc = feed.get("noteCard", {})
        dt = re.sub(r'\s+', '', nc.get("displayTitle", ""))
        uid = nc.get("user", {}).get("userId", "")
        if uid == MY_USER_ID and (dt == clean_title or clean_title in dt or dt in clean_title):
            fid = feed.get("id", "")
            tok = feed.get("xsecToken", "")
            if fid:
                log.info("找到 feed_id: %s (自己的笔记)", fid)
                return fid, tok
    # 第二轮：标题模糊匹配（不限用户）
    for feed in feeds:
        nc = feed.get("noteCard", {})
        dt = re.sub(r'\s+', '', nc.get("displayTitle", ""))
        if clean_title in dt or dt in clean_title:
            fid = feed.get("id", "")
            tok = feed.get("xsecToken", "")
            if fid:
                log.info("找到 feed_id（模糊匹配）: %s", fid)
                return fid, tok
    return "", ""


def find_feed_id(title: str) -> tuple[str, str]:
    """
    发布成功后搜索自己的文章，获取 feed_id 和 xsec_token。
    策略：用标题前 10 字搜索（短关键词更快），匹配时优先过滤自己的 userId。
    返回 (feed_id, xsec_token)，失败返回 ("", "")
    """
    keyword = title[:10]
    try:
        result = call_tool("search_feeds", {"keyword": keyword})
        feeds = _parse_feeds_response(result)
        fid, tok = _match_feed(feeds, title)
        if fid:
            return fid, tok
        log.warning("未找到匹配的 feed，关键词: %s", keyword)
        return "", ""
    except Exception as e:
        log.warning("搜索 feed_id 失败: %s", e)
        return "", ""


# ─── 发布文章 ─────────────────────────────────────────────────────────────────
def publish_article(article: dict, index: int = 0) -> bool:
    try:
        # 生成封面图（传入 category 选择模板，full_content 用于提取要点）
        cover_path = generate_cover(
            article["title"],
            content=article.get("full_content", article["content"]),
            index=index,
            category=article.get("category", "options"),
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
            # 检查 isError 标志
            if res_content.get("isError"):
                inner = res_content.get("content", [])
                text = inner[0].get("text", "") if inner else ""
                log.error("发布失败 (isError=true): %s", text[:200])
                return False
            inner = res_content.get("content", [])
            if isinstance(inner, list) and inner:
                text = inner[0].get("text", "")
                if ("error" in text.lower() or "失败" in text) and "成功" not in text:
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

    # ── 1+1 分类均衡：优先选与今日上一篇不同 category 的文章 ──────────────
    today_cats = get_today_published_categories(state)
    last_cat = today_cats[-1] if today_cats else ""
    target = None
    if last_cat:
        for p in pending:
            cat = get_article_category(p)
            if cat and cat != last_cat:
                target = p
                log.info("分类均衡：今日已发 [%s]，选 [%s] 文章", last_cat, cat)
                break
    if target is None:
        target = pending[0]
    log.info("准备发布: %s", target.name)

    article = parse_article(target)
    log.info("标题: %s", article["title"])
    log.info("tags: %s", article["tags"])
    log.info("正文长度: %d 字符", len(article["content"]))

    published_count = len(state["published"])
    success = publish_article(article, index=published_count)

    if success:
        # 等待让小红书索引生效后再搜索 feed_id
        import time
        time.sleep(15)
        feed_id, xsec_token = find_feed_id(article["title"])

        entry = {
            "file": str(target),
            "title": article["title"],
            "theme_id": article.get("theme_id") or "unknown",
            "category": article.get("category") or "",
            "published_at": datetime.now().isoformat(timespec="seconds"),
            "feed_id": feed_id,
            "xsec_token": xsec_token,
            "checkpoints": {},
        }
        state["published"].append(entry)
        save_state(state)

        # 移动文件到「已发布」文件夹
        published_dir = Path("/Users/jarvis/xiaohongshu-mcp/vault/已发布")
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
