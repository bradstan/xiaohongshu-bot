#!/usr/bin/env python3
"""
多平台素材采集模块 (x-reader 风格)
所有平台采集后统一输出标准化素材格式，供 research.py 消费。

支持平台：
- 小红书（MCP server）
- YouTube（字幕提取）
- Reddit（r/options 等）
- RSS（期权博客/公众号）
- Web（Tavily 通用搜索）
"""

import json
import re
import logging
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict

log = logging.getLogger(__name__)

# ─── 统一素材格式 ────────────────────────────────────────────────────────────
@dataclass
class Material:
    """标准化素材，不管来自哪个平台都长这样"""
    title: str
    content: str          # 正文/字幕/帖子内容
    source: str           # 平台名：小红书/YouTube/Reddit/RSS/Web
    url: str = ""         # 原始链接
    author: str = ""
    engagement: int = 0   # 互动量（收藏/赞/播放量，统一成一个排序指标）
    collected_at: str = ""  # 采集时间

    def to_dict(self) -> dict:
        return asdict(self)


# ─── MCP 工具（小红书复用） ──────────────────────────────────────────────────
MCP_URL    = "http://localhost:18060/mcp"
MCP_ACCEPT = "application/json, text/event-stream"
_session_id: Optional[str] = None


def _get_mcp_session() -> str:
    global _session_id
    if _session_id:
        return _session_id
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "collector", "version": "1.0"},
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


def _mcp_call(method: str, params: dict, req_id: int = 2) -> dict:
    sid = _get_mcp_session()
    payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        MCP_URL, data=payload,
        headers={"Content-Type": "application/json", "Accept": MCP_ACCEPT, "mcp-session-id": sid},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _mcp_tool(name: str, args: dict) -> dict:
    return _mcp_call("tools/call", {"name": name, "arguments": args})


# ═══════════════════════════════════════════════════════════════════════════════
# 采集器 1：小红书
# ═══════════════════════════════════════════════════════════════════════════════
def _get_xhs_content(feed_id: str, xsec_token: str) -> Optional[str]:
    try:
        result = _mcp_tool("get_feed_detail", {"feed_id": feed_id, "xsec_token": xsec_token})
        note = (result.get("data", {}).get("note", {}) or
                result.get("result", {}).get("data", {}).get("note", {}))
        desc = note.get("desc", "")
        return desc if desc else None
    except Exception as e:
        log.warning("获取小红书笔记详情失败: %s", e)
        return None


def collect_xiaohongshu(keywords: List[str], max_total: int = 20) -> List[Material]:
    """多关键词 × 多排序搜索小红书，去重后返回标准化素材"""
    all_materials = []
    seen_titles = set()
    per_query = max(5, max_total // max(len(keywords) * 2, 1))

    for kw in keywords:
        for sort_by in ["最多收藏", "最多点赞"]:
            try:
                result = _mcp_tool("search_feeds", {
                    "keyword": kw,
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

                for feed in feeds[:per_query]:
                    note_card = feed.get("noteCard", {})
                    title = note_card.get("displayTitle", "") or note_card.get("title", "")
                    interact = note_card.get("interactInfo", {})
                    feed_id = feed.get("id", "")
                    xsec_token = feed.get("xsecToken", "")

                    if not title or not feed_id:
                        continue
                    clean = re.sub(r'\s+', '', title)
                    if clean in seen_titles:
                        continue
                    seen_titles.add(clean)

                    content = _get_xhs_content(feed_id, xsec_token) or ""
                    collected = int(str(interact.get("collectedCount", 0)).replace(",", "") or 0)
                    liked = int(str(interact.get("likedCount", 0)).replace(",", "") or 0)

                    all_materials.append(Material(
                        title=title,
                        content=content[:800],
                        source="小红书",
                        engagement=collected + liked,
                        collected_at=datetime.now().isoformat(timespec="seconds"),
                    ))

                if len(all_materials) >= max_total:
                    break
            except Exception as e:
                log.warning("小红书搜索 [%s/%s] 失败: %s", kw, sort_by, e)

        if len(all_materials) >= max_total:
            break

    all_materials.sort(key=lambda m: m.engagement, reverse=True)
    return all_materials[:max_total]


# ═══════════════════════════════════════════════════════════════════════════════
# 采集器 2：YouTube（字幕提取）
# ═══════════════════════════════════════════════════════════════════════════════
def collect_youtube(keywords: List[str], max_total: int = 20) -> List[Material]:
    """
    搜索 YouTube 期权教学视频，提取字幕作为素材。
    用 yt-dlp 搜索 + youtube_transcript_api 提取字幕。
    """
    import subprocess

    materials = []
    seen_ids = set()

    for kw in keywords:
        if len(materials) >= max_total:
            break
        search_query = f"ytsearch10:{kw}"
        try:
            result = subprocess.run(
                ["yt-dlp", "--flat-playlist", "--dump-json", search_query],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                log.warning("yt-dlp 搜索失败: %s", result.stderr[:200])
                continue

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    video = json.loads(line)
                except Exception:
                    continue

                vid = video.get("id", "")
                title = video.get("title", "")
                view_count = video.get("view_count", 0) or 0
                uploader = video.get("uploader", "")

                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)

                # 提取字幕
                transcript_text = _get_youtube_transcript(vid)
                if not transcript_text:
                    continue

                materials.append(Material(
                    title=title,
                    content=transcript_text[:2000],
                    source="YouTube",
                    url=f"https://youtube.com/watch?v={vid}",
                    author=uploader,
                    engagement=view_count,
                    collected_at=datetime.now().isoformat(timespec="seconds"),
                ))

                if len(materials) >= max_total:
                    break
        except subprocess.TimeoutExpired:
            log.warning("yt-dlp 搜索超时: %s", kw)
        except Exception as e:
            log.warning("YouTube 搜索异常 [%s]: %s", kw, e)

    materials.sort(key=lambda m: m.engagement, reverse=True)
    return materials[:max_total]


def _get_youtube_transcript(video_id: str) -> Optional[str]:
    """提取 YouTube 视频字幕（优先中文，其次英文）"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # 优先中文字幕
        transcript = None
        for lang in ["zh-Hans", "zh-Hant", "zh", "zh-CN", "zh-TW"]:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except Exception:
                continue

        # 其次英文
        if not transcript:
            try:
                transcript = transcript_list.find_transcript(["en"])
            except Exception:
                # 尝试自动生成的字幕
                try:
                    generated = transcript_list.find_generated_transcript(["en"])
                    transcript = generated
                except Exception:
                    pass

        if not transcript:
            return None

        entries = transcript.fetch()
        text = " ".join(e.get("text", "") if isinstance(e, dict) else str(e) for e in entries)
        return text.strip() if text.strip() else None

    except Exception as e:
        log.debug("字幕提取失败 [%s]: %s", video_id, e)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 采集器 3：Reddit
# ═══════════════════════════════════════════════════════════════════════════════
TAVILY_API_KEY = "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"
TAVILY_URL     = "https://api.tavily.com/search"


def _tavily_search(query: str, max_results: int = 10) -> List[dict]:
    """Tavily 搜索"""
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
        return data.get("results", [])[:max_results]
    except Exception as e:
        log.warning("Tavily 搜索失败 [%s]: %s", query, e)
        return []


def collect_reddit(keywords: List[str], max_total: int = 20) -> List[Material]:
    """从 Reddit 期权相关 subreddit 搜索高质量讨论帖"""
    subreddits = ["r/options", "r/thetagang", "r/wallstreetbets", "r/investing"]
    materials = []
    seen_urls = set()

    for kw in keywords:
        for sub in subreddits:
            if len(materials) >= max_total:
                break
            query = f"site:reddit.com {sub} {kw}"
            results = _tavily_search(query, max_results=5)
            for item in results:
                url = item.get("url", "")
                if url in seen_urls or not url:
                    continue
                seen_urls.add(url)
                materials.append(Material(
                    title=item.get("title", ""),
                    content=item.get("content", "")[:800],
                    source="Reddit",
                    url=url,
                    engagement=0,  # Tavily 不返回 score
                    collected_at=datetime.now().isoformat(timespec="seconds"),
                ))
        if len(materials) >= max_total:
            break

    return materials[:max_total]


# ═══════════════════════════════════════════════════════════════════════════════
# 采集器 4：RSS 订阅（期权博客）
# ═══════════════════════════════════════════════════════════════════════════════
# 优质期权科普 RSS 源
DEFAULT_RSS_FEEDS = [
    "https://optionalpha.com/blog/feed",
    "https://www.tastylive.com/feeds/shows.rss",
    "https://theoptionsinsider.com/feed/",
]


def collect_rss(feed_urls: List[str] = None, max_per_feed: int = 5,
                max_total: int = 20) -> List[Material]:
    """从 RSS 源采集期权相关文章"""
    import feedparser

    if feed_urls is None:
        feed_urls = DEFAULT_RSS_FEEDS

    materials = []
    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "")
                # 提取纯文本内容
                summary = entry.get("summary", "") or entry.get("description", "")
                # 去 HTML 标签
                content = re.sub(r'<[^>]+>', '', summary).strip()

                materials.append(Material(
                    title=title,
                    content=content[:800],
                    source="RSS",
                    url=entry.get("link", ""),
                    author=entry.get("author", feed.feed.get("title", "")),
                    engagement=0,
                    collected_at=datetime.now().isoformat(timespec="seconds"),
                ))
        except Exception as e:
            log.warning("RSS 采集失败 [%s]: %s", url, e)

    return materials[:max_total]


# ═══════════════════════════════════════════════════════════════════════════════
# 采集器 5：Web 通用搜索
# ═══════════════════════════════════════════════════════════════════════════════
def collect_web(keywords: List[str], max_total: int = 20) -> List[Material]:
    """Tavily 通用 Web 搜索，采集期权科普文章"""
    materials = []
    seen_urls = set()

    queries = []
    for kw in keywords:
        queries.append(f"options trading {kw} tutorial guide")
        queries.append(f"期权 {kw} 教程 科普")

    for query in queries:
        if len(materials) >= max_total:
            break
        results = _tavily_search(query, max_results=5)
        for item in results:
            url = item.get("url", "")
            if url in seen_urls or not url:
                continue
            # 排除 Reddit（已单独采集）
            if "reddit.com" in url:
                continue
            seen_urls.add(url)
            materials.append(Material(
                title=item.get("title", ""),
                content=item.get("content", "")[:800],
                source="Web",
                url=url,
                engagement=0,
                collected_at=datetime.now().isoformat(timespec="seconds"),
            ))

    return materials[:max_total]


# ═══════════════════════════════════════════════════════════════════════════════
# 聚合入口
# ═══════════════════════════════════════════════════════════════════════════════
def collect_all(keywords: List[str],
                enable_xhs: bool = True,
                enable_youtube: bool = True,
                enable_reddit: bool = True,
                enable_rss: bool = True,
                enable_web: bool = True,
                max_per_source: int = 20) -> Dict[str, List[Material]]:
    """
    全平台采集，返回按来源分组的素材。
    每个来源独立采集，某个失败不影响其他。
    """
    result = {}

    if enable_xhs:
        log.info("  [小红书] 采集中...")
        try:
            result["小红书"] = collect_xiaohongshu(keywords, max_per_source)
            log.info("  [小红书] %d 条", len(result["小红书"]))
        except Exception as e:
            log.warning("  [小红书] 采集失败: %s", e)
            result["小红书"] = []

    if enable_youtube:
        log.info("  [YouTube] 采集中...")
        try:
            yt_keywords = [f"options trading {kw}" for kw in keywords[:3]]
            result["YouTube"] = collect_youtube(yt_keywords, max_per_source)
            log.info("  [YouTube] %d 条", len(result["YouTube"]))
        except Exception as e:
            log.warning("  [YouTube] 采集失败: %s", e)
            result["YouTube"] = []

    if enable_reddit:
        log.info("  [Reddit] 采集中...")
        try:
            result["Reddit"] = collect_reddit(keywords, max_per_source)
            log.info("  [Reddit] %d 条", len(result["Reddit"]))
        except Exception as e:
            log.warning("  [Reddit] 采集失败: %s", e)
            result["Reddit"] = []

    if enable_rss:
        log.info("  [RSS] 采集中...")
        try:
            result["RSS"] = collect_rss(max_total=max_per_source)
            log.info("  [RSS] %d 条", len(result["RSS"]))
        except Exception as e:
            log.warning("  [RSS] 采集失败: %s", e)
            result["RSS"] = []

    if enable_web:
        log.info("  [Web] 采集中...")
        try:
            result["Web"] = collect_web(keywords, max_per_source)
            log.info("  [Web] %d 条", len(result["Web"]))
        except Exception as e:
            log.warning("  [Web] 采集失败: %s", e)
            result["Web"] = []

    total = sum(len(v) for v in result.values())
    log.info("  采集完成：共 %d 条素材（%s）", total,
             " + ".join(f"{k} {len(v)}" for k, v in result.items() if v))
    return result


def materials_to_prompt_text(materials_by_source: Dict[str, List[Material]],
                             max_per_source: int = 10) -> str:
    """
    把多源素材转成 prompt 可用的文本。
    每个来源取 top N，正文只取前 400 字。
    """
    sections = []
    for source, materials in materials_by_source.items():
        if not materials:
            continue
        lines = [f"\n## {source}素材（共 {len(materials)} 条，展示前 {min(len(materials), max_per_source)} 条）\n"]
        for i, m in enumerate(materials[:max_per_source], 1):
            lines.append(f"--- {source}参考{i} ---")
            lines.append(f"标题：{m.title}")
            if m.author:
                lines.append(f"作者：{m.author}")
            if m.content:
                lines.append(f"内容摘要：{m.content[:400]}")
            lines.append("")
        sections.append("\n".join(lines))

    return "\n".join(sections) if sections else "暂无参考素材"


# ─── CLI 测试 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)s  %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])

    test_keywords = ["期权入门", "options basics", "Delta Theta"]
    print("=" * 60)
    print("多平台素材采集测试")
    print("=" * 60)

    results = collect_all(test_keywords, max_per_source=5)
    for source, materials in results.items():
        print(f"\n{'─' * 40}")
        print(f"📌 {source}: {len(materials)} 条")
        for m in materials[:3]:
            print(f"  • {m.title[:50]}...")
            print(f"    内容: {m.content[:100]}...")
            print()
