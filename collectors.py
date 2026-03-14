#!/usr/bin/env python3
"""
多平台素材采集模块 (x-reader 风格)
所有平台采集后统一输出标准化素材格式，供 research.py 消费。

支持平台：
- 小红书（MCP server）
- YouTube（字幕提取）
- Twitter/X（agent-reach）
- Reddit（agent-reach，fallback Tavily）
- RSS（期权博客/公众号）
- Web（Tavily 通用搜索）
"""

import json
import os
import re
import subprocess
import logging
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict

log = logging.getLogger(__name__)

# ─── agent-reach CLI ──────────────────────────────────────────────────────────
AGENT_REACH_BIN = "/Users/jarvis/.local/bin/agent-reach"
_AR_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/Users/jarvis/.local/bin:" + os.environ.get("PATH", ""),
}


def _cleanup_rod_chromium() -> None:
    """强制清理 agent-reach (rod) 遗留的 Chromium 僵尸进程。"""
    try:
        subprocess.run(
            ["pkill", "-9", "-f", "rod/browser/chromium"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _agent_reach_search(subcommand: str, query: str, timeout: int = 30) -> list:
    """
    调用 agent-reach <subcommand> <query>，解析编号列表输出为 dict 列表。
    支持 search-twitter / search-reddit / search-xhs / search-youtube 等。
    search-xhs 使用 rod 驱动 Chromium，调用前后均清理僵尸进程。
    """
    is_xhs = (subcommand == "search-xhs")
    if is_xhs:
        _cleanup_rod_chromium()
    try:
        result = subprocess.run(
            [AGENT_REACH_BIN, subcommand, query],
            capture_output=True, text=True, timeout=timeout, env=_AR_ENV,
        )
        if result.returncode != 0:
            log.warning("agent-reach %s 失败: %s", subcommand, result.stderr[:200])
            return []
        return _parse_ar_output(result.stdout)
    except subprocess.TimeoutExpired:
        log.warning("agent-reach %s 超时: %s", subcommand, query)
        return []
    except FileNotFoundError:
        log.warning("agent-reach 未找到，跳过 %s", subcommand)
        return []
    except Exception as e:
        log.warning("agent-reach %s 异常: %s", subcommand, e)
        return []
    finally:
        if is_xhs:
            _cleanup_rod_chromium()


def _parse_ar_output(text: str) -> list:
    """
    解析 agent-reach 的编号列表输出，格式示例：
      1. 标题
         🔗 https://...
         👤 作者 · ❤ 132
         正文摘要...
    """
    items = []
    entries = re.split(r'\n(?=\d+\. )', text.strip())
    for entry in entries:
        lines = [l.strip() for l in entry.strip().split('\n') if l.strip()]
        if not lines:
            continue
        title_m = re.match(r'^\d+\.\s+(.+)$', lines[0])
        title = title_m.group(1) if title_m else lines[0]

        url, author, engagement, content_parts = "", "", 0, []
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
            elif line.startswith('⏱') or line.startswith('👁'):
                pass  # YouTube 时长/播放量已在 👤 行处理
            else:
                content_parts.append(line)

        items.append({
            "title": title,
            "url": url,
            "author": author,
            "engagement": engagement,
            "content": " ".join(content_parts),
        })
    return items


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


# ═══════════════════════════════════════════════════════════════════════════════
# 采集器 1：小红书
# ═══════════════════════════════════════════════════════════════════════════════
def collect_xiaohongshu(keywords: List[str], max_total: int = 20) -> List[Material]:
    """
    多关键词搜索小红书，通过 agent-reach (mcporter) 稳定获取结果。
    返回标题 + 互动数 + URL，不逐条拉全文（避免超时）。
    """
    all_materials = []
    seen_urls = set()

    for kw in keywords:
        if len(all_materials) >= max_total:
            break
        items = _agent_reach_search("search-xhs", kw, timeout=60)
        for item in items:
            url = item.get("url", "")
            key = url or item["title"]
            if key in seen_urls or not item["title"]:
                continue
            seen_urls.add(key)
            all_materials.append(Material(
                title=item["title"],
                content=item.get("content", ""),
                source="小红书",
                url=url,
                author=item.get("author", ""),
                engagement=item.get("engagement", 0),
                collected_at=datetime.now().isoformat(timespec="seconds"),
            ))
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
    """从 Reddit 期权相关 subreddit 搜索高质量讨论帖（agent-reach 优先，Tavily 兜底）"""
    materials = []
    seen_urls = set()

    for kw in keywords[:4]:
        if len(materials) >= max_total:
            break
        query = f"options {kw}"
        items = _agent_reach_search("search-reddit", query, timeout=30)

        if not items:
            # fallback: Tavily site:reddit.com
            log.debug("Reddit agent-reach 无结果，fallback Tavily: %s", kw)
            for sub in ["r/options", "r/thetagang"]:
                raw = _tavily_search(f"site:reddit.com {sub} {kw}", max_results=5)
                items += [{"title": r.get("title",""), "url": r.get("url",""),
                           "author": "", "engagement": 0, "content": r.get("content","")[:600]}
                          for r in raw]

        for item in items:
            url = item.get("url", "")
            if url in seen_urls or not url:
                continue
            seen_urls.add(url)
            materials.append(Material(
                title=item["title"],
                content=item["content"][:800],
                source="Reddit",
                url=url,
                author=item.get("author", ""),
                engagement=item.get("engagement", 0),
                collected_at=datetime.now().isoformat(timespec="seconds"),
            ))
            if len(materials) >= max_total:
                break

    return materials[:max_total]


# ═══════════════════════════════════════════════════════════════════════════════
# 采集器 3b：Twitter/X（agent-reach）
# ═══════════════════════════════════════════════════════════════════════════════
def collect_twitter(keywords: List[str], max_total: int = 20) -> List[Material]:
    """搜索 Twitter/X 上期权相关的热门讨论（英文为主，可作为选题信号）"""
    materials = []
    seen_urls = set()

    for kw in keywords[:4]:
        if len(materials) >= max_total:
            break
        query = f"options trading {kw}" if re.search(r'[a-zA-Z]', kw) else f"{kw} options"
        items = _agent_reach_search("search-twitter", query, timeout=30)

        for item in items:
            url = item.get("url", "")
            if url in seen_urls or not url:
                continue
            seen_urls.add(url)
            materials.append(Material(
                title=item["title"],
                content=item["content"][:800],
                source="Twitter",
                url=url,
                author=item.get("author", ""),
                engagement=item.get("engagement", 0),
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
                enable_twitter: bool = True,
                enable_rss: bool = True,
                enable_web: bool = True,
                max_per_source: int = 20,
                source_limits: dict = None) -> Dict[str, List[Material]]:
    """
    全平台采集，返回按来源分组的素材。
    source_limits 可单独覆盖各来源限额，例如：
      {"小红书": 25, "Twitter": 30, "Reddit": 15}
    未在 source_limits 中指定的来源使用 max_per_source。
    """
    sl = source_limits or {}

    def _lim(key: str) -> int:
        return sl.get(key, max_per_source)

    result = {}

    if enable_xhs:
        log.info("  [小红书] 采集中...")
        try:
            result["小红书"] = collect_xiaohongshu(keywords, _lim("小红书"))
            log.info("  [小红书] %d 条", len(result["小红书"]))
        except Exception as e:
            log.warning("  [小红书] 采集失败: %s", e)
            result["小红书"] = []

    if enable_youtube:
        log.info("  [YouTube] 采集中...")
        try:
            yt_kw = [f"{kw} tutorial" for kw in keywords[:3]]
            result["YouTube"] = collect_youtube(yt_kw, _lim("YouTube"))
            log.info("  [YouTube] %d 条", len(result["YouTube"]))
        except Exception as e:
            log.warning("  [YouTube] 采集失败: %s", e)
            result["YouTube"] = []

    if enable_reddit:
        log.info("  [Reddit] 采集中...")
        try:
            result["Reddit"] = collect_reddit(keywords, _lim("Reddit"))
            log.info("  [Reddit] %d 条", len(result["Reddit"]))
        except Exception as e:
            log.warning("  [Reddit] 采集失败: %s", e)
            result["Reddit"] = []

    if enable_twitter:
        log.info("  [Twitter] 采集中...")
        try:
            result["Twitter"] = collect_twitter(keywords, _lim("Twitter"))
            log.info("  [Twitter] %d 条", len(result["Twitter"]))
        except Exception as e:
            log.warning("  [Twitter] 采集失败: %s", e)
            result["Twitter"] = []

    if enable_rss:
        log.info("  [RSS] 采集中...")
        try:
            result["RSS"] = collect_rss(max_total=_lim("RSS"))
            log.info("  [RSS] %d 条", len(result["RSS"]))
        except Exception as e:
            log.warning("  [RSS] 采集失败: %s", e)
            result["RSS"] = []

    if enable_web:
        log.info("  [Web] 采集中...")
        try:
            result["Web"] = collect_web(keywords, _lim("Web"))
            log.info("  [Web] %d 条", len(result["Web"]))
        except Exception as e:
            log.warning("  [Web] 采集失败: %s", e)
            result["Web"] = []

    total = sum(len(v) for v in result.values())
    log.info("  采集完成：共 %d 条素材（%s）", total,
             " + ".join(f"{k} {len(v)}" for k, v in result.items() if v))
    # 兜底：确保所有 rod/Chromium 进程已退出
    if enable_xhs:
        _cleanup_rod_chromium()
    return result


def materials_to_prompt_text(materials_by_source: Dict[str, List[Material]],
                             max_per_source: int = 10,
                             source_order: list = None) -> str:
    """
    把多源素材转成 prompt 可用的文本。
    source_order 指定来源展示顺序（排前的来源在 prompt 中更靠前，
    Claude 会优先参考）。未在 source_order 中的来源追加到末尾。
    """
    # 按 source_order 排列来源
    all_sources = list(materials_by_source.keys())
    if source_order:
        ordered = [s for s in source_order if s in materials_by_source]
        ordered += [s for s in all_sources if s not in ordered]
    else:
        ordered = all_sources

    sections = []
    for source in ordered:
        materials = materials_by_source.get(source, [])
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
