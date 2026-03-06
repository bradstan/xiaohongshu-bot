#!/usr/bin/env python3
"""
选题调研脚本 (trend_scout.py)

功能：
  1. 用 agent-reach 横扫 Twitter + Reddit + 小红书，采集各平台当前热门内容
  2. 对比 topics.json + 历史发布记录，找出"趋势内容 vs 已有覆盖"的交叉点
  3. 调用 Claude 分析：哪些方向在涨热度、哪些角度是空白、给出选题建议
  4. 输出 Markdown 报告到「待策划/」文件夹，供人工审阅或 research.py 消费

典型用法：
  python trend_scout.py              # 全量调研，生成报告
  python trend_scout.py --dry-run    # 只采集数据、不调用 LLM，输出原始素材
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# cron 环境 PATH 修复
if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/Users/jarvis/.local/bin:" + os.environ.get("PATH", "")

# ─── 路径配置 ─────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path("/Users/jarvis/xiaohongshu-mcp")
TOPICS_FILE   = SCRIPT_DIR / "topics.json"
STATE_FILE    = SCRIPT_DIR / "published.json"
SCOUT_DIR     = Path("/Users/jarvis/Documents/小红书/待策划")
LOG_FILE      = SCRIPT_DIR / "trend_scout.log"
AGENT_REACH   = "/Users/jarvis/.local/bin/agent-reach"
AR_ENV        = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/Users/jarvis/.local/bin:" + os.environ.get("PATH", ""),
}

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


# ─── agent-reach 工具函数 ─────────────────────────────────────────────────────
def _cleanup_rod_chromium() -> None:
    """强制清理 rod 遗留的 Chromium 僵尸进程。"""
    try:
        subprocess.run(["pkill", "-9", "-f", "rod/browser/chromium"],
                       capture_output=True, timeout=5)
    except Exception:
        pass


def _ar(subcommand: str, query: str, timeout: int = 30) -> List[dict]:
    """运行 agent-reach 子命令，解析编号列表结果。
    search-xhs 调用前后均清理 Chromium 僵尸进程。
    """
    is_xhs = (subcommand == "search-xhs")
    if is_xhs:
        _cleanup_rod_chromium()
    try:
        result = subprocess.run(
            [AGENT_REACH, subcommand, query],
            capture_output=True, text=True, timeout=timeout, env=AR_ENV,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        return _parse_ar(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        log.warning("agent-reach %s [%s] 失败: %s", subcommand, query, e)
        return []
    finally:
        if is_xhs:
            _cleanup_rod_chromium()


def _parse_ar(text: str) -> List[dict]:
    """解析 agent-reach 编号列表输出 → list of dict。"""
    items = []
    for entry in re.split(r'\n(?=\d+\. )', text.strip()):
        lines = [l.strip() for l in entry.split('\n') if l.strip()]
        if not lines:
            continue
        m = re.match(r'^\d+\.\s+(.+)$', lines[0])
        title = m.group(1) if m else lines[0]
        url, author, engagement, extra = "", "", 0, []
        for line in lines[1:]:
            if line.startswith('🔗'):
                url = line.replace('🔗', '').strip()
            elif line.startswith('👤'):
                parts = re.split(r'·', line.replace('👤', ''))
                author = parts[0].strip()
                for p in parts[1:]:
                    nm = re.search(r'([\d,]+)', p)
                    if nm:
                        try:
                            engagement = max(engagement, int(nm.group(1).replace(',', '')))
                        except ValueError:
                            pass
            else:
                extra.append(line)
        items.append({"title": title, "url": url, "author": author,
                      "engagement": engagement, "snippet": " ".join(extra)})
    return items


# ─── 数据加载 ─────────────────────────────────────────────────────────────────
def load_topics() -> dict:
    with TOPICS_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def load_published_titles() -> List[str]:
    if not STATE_FILE.exists():
        return []
    with STATE_FILE.open(encoding="utf-8") as f:
        state = json.load(f)
    return [e.get("title", "") for e in state.get("published", []) if e.get("title")]


# ─── 多平台调研 ───────────────────────────────────────────────────────────────
def scout_platform(platform: str, queries: List[str], max_per_query: int = 8) -> List[dict]:
    """对某平台执行多个查询，去重合并结果。"""
    seen, results = set(), []
    cmd_map = {
        "twitter":  "search-twitter",
        "reddit":   "search-reddit",
        "xhs":      "search-xhs",
        "youtube":  "search-youtube",
    }
    cmd = cmd_map.get(platform, f"search-{platform}")
    timeout = {"xhs": 60, "youtube": 45}.get(platform, 30)
    for q in queries:
        for item in _ar(cmd, q, timeout=timeout)[:max_per_query]:
            key = item["url"] or item["title"]
            if key and key not in seen:
                seen.add(key)
                item["query"] = q
                item["platform"] = platform
                results.append(item)
    return results


def run_scout(themes: List[dict]) -> Dict[str, Dict[str, List[dict]]]:
    """
    对每个 theme，在 Twitter / Reddit / 小红书 三个平台各采集一批数据。
    返回：{ theme_id: { platform: [items] } }
    """
    all_data: Dict[str, Dict[str, List[dict]]] = {}

    for theme in themes:
        tid = theme["id"]
        name = theme["name"]
        keywords = theme.get("keywords", [])
        log.info("调研主题: %s (%s)", name, tid)

        # 构建多平台查询（按分类差异化）
        category = theme.get("category", "options")
        en_kw  = [kw for kw in keywords if re.search(r'[a-zA-Z]', kw) and not re.search(r'[\u4e00-\u9fff]', kw)][:3]
        zh_kw  = [kw for kw in keywords if not re.search(r'[a-zA-Z]', kw)][:3]
        # 含中文的混合词（如 "OpenClaw玩法"）归为中文关键词
        mixed_kw = [kw for kw in keywords if re.search(r'[a-zA-Z]', kw) and re.search(r'[\u4e00-\u9fff]', kw)][:2]
        zh_kw = (zh_kw + mixed_kw)[:4]

        if category == "ai_tools":
            twitter_queries = [f"{kw} tutorial tips" for kw in en_kw[:3]] + \
                              [f"{name} how to use"]
            reddit_queries  = [f"{kw} review" for kw in en_kw[:3]] + \
                              [f"{name} tips"]
            xhs_queries     = zh_kw + [f"AI工具 {kw}" for kw in zh_kw[:2]]
        else:
            twitter_queries = [f"options trading {kw}" for kw in en_kw] + \
                              [f"{kw} stock options" for kw in en_kw[:2]]
            reddit_queries  = [f"options {kw}" for kw in en_kw] + \
                              [f"options trading {name}"]
            xhs_queries     = zh_kw + [f"美股期权 {kw}" for kw in zh_kw[:2]]

        all_data[tid] = {
            "twitter": scout_platform("twitter", twitter_queries[:4]),
            "reddit":  scout_platform("reddit",  reddit_queries[:4]),
            "xhs":     scout_platform("xhs",     xhs_queries[:4]),
        }
        for platform, items in all_data[tid].items():
            log.info("  %s/%s: %d 条", tid, platform, len(items))

    return all_data


# ─── 格式化输出（供 LLM 分析） ────────────────────────────────────────────────
def format_scout_data(scout_data: Dict[str, Dict[str, List[dict]]],
                      topics: dict, published_titles: List[str]) -> str:
    """把采集数据整理成 LLM prompt 用的结构化文本。"""
    themes = {t["id"]: t for t in topics.get("themes", [])}
    lines = []

    lines.append(f"# 多平台选题调研数据")
    lines.append(f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    lines.append("## 账号历史已发内容（避免重复）")
    for t in published_titles[-20:]:
        lines.append(f"- {t}")
    lines.append("")

    for tid, platforms in scout_data.items():
        theme = themes.get(tid, {})
        lines.append(f"## 主题：{theme.get('name', tid)}")
        lines.append(f"说明：{theme.get('description', '')}\n")

        for platform, items in platforms.items():
            if not items:
                continue
            platform_label = {"twitter": "Twitter/X", "reddit": "Reddit",
                              "xhs": "小红书"}.get(platform, platform)
            lines.append(f"### {platform_label}（{len(items)} 条）")
            for item in items[:6]:
                eng = f" | 互动:{item['engagement']}" if item['engagement'] else ""
                auth = f" | {item['author']}" if item['author'] else ""
                lines.append(f"- **{item['title'][:60]}**{auth}{eng}")
                if item.get("snippet"):
                    lines.append(f"  > {item['snippet'][:120]}")
            lines.append("")

    return "\n".join(lines)


# ─── LLM 分析 ─────────────────────────────────────────────────────────────────
def analyze_with_llm(scout_text: str, topics: dict) -> Optional[str]:
    """调用 Claude 分析调研数据，生成选题建议报告。"""
    from llm import call_llm

    account_desc = topics.get("account_description", "")
    notes_per_plan = topics.get("notes_per_plan", 5)

    prompt = f"""你是一个小红书内容策划专家，负责分析跨平台数据并制定选题方向。

## 账号定位
{account_desc}

## 多平台调研数据
{scout_text}

## 任务
请仔细分析上面的多平台数据，完成以下三个部分：

### 1. 趋势洞察（3-5条）
- 当前英文社区（Twitter/Reddit）什么期权话题最热？
- 中文社区（小红书）什么内容互动最高？
- 两个市场之间有什么信息差或时差机会？

### 2. 内容空白分析
对照历史已发内容，找出以下两类机会：
- 【热门但未覆盖】：社区在讨论但账号还没写过的话题
- 【有内容但可深化】：账号写过但可以用新角度重新包装的话题

### 3. 下一批选题建议（{notes_per_plan}个）
为每个选题提供：
- 🎯 **标题**（20字以内，带数字或钩子）
- 📌 **一句话说明**：这篇写什么、为什么现在写
- 💡 **切入角度**：从哪个场景或痛点切入
- 📊 **数据依据**：哪条调研结果支撑这个选题

格式要清晰，直接给结论，不要废话。"""

    log.info("调用 Claude 分析调研数据...")
    return call_llm(prompt, max_tokens=3000)


# ─── content_plan.json 输出 ───────────────────────────────────────────────────
CONTENT_PLAN_FILE = SCRIPT_DIR / "state" / "content_plan.json"

def save_content_plan(analysis: str, topics: dict) -> None:
    """
    从 LLM 分析文本中提取选题建议，保存为机器可读的 content_plan.json。
    research.py 读取此文件，在 pick_themes() 中优先选这些主题。
    """
    valid_ids = {t["id"] for t in topics.get("themes", [])}

    # 按优先级顺序从分析文本中找到 theme id 的提及
    suggested: List[dict] = []
    seen: set = set()

    # 从「下一批选题建议」章节提取主题 id
    for tid in valid_ids:
        # 匹配 theme name 或 theme id 的提及
        theme_obj = next((t for t in topics["themes"] if t["id"] == tid), None)
        if not theme_obj:
            continue
        name = theme_obj["name"]
        # 在分析文本中查找该主题（按 name 或 id）
        if name in analysis or tid in analysis:
            if tid not in seen:
                seen.add(tid)
                # 提取紧跟 name 后的第一条切入角度说明（取「📌」行内容）
                angle = ""
                for line in analysis.split("\n"):
                    if name in line and "📌" in line:
                        angle = re.sub(r".*📌[^\u4e00-\u9fff]*", "", line).strip()
                        break
                suggested.append({"theme_id": tid, "angle": angle,
                                   "priority": len(suggested) + 1})

    plan = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "expires": "",  # research.py 按 date 判断新鲜度（3天内有效）
        "suggested": suggested,
    }
    CONTENT_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTENT_PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    log.info("content_plan.json 已更新：%d 个建议主题", len(suggested))


# ─── 报告输出 ──────────────────────────────────────────────────────────────────
def save_report(analysis: Optional[str], scout_text: str,
                scout_data: Dict, dry_run: bool = False) -> Path:
    """保存调研报告到「待策划/」文件夹。"""
    SCOUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    filename = f"选题调研_{now.strftime('%Y-%m-%d_%H%M')}.md"
    out_path = SCOUT_DIR / filename

    total = sum(len(v) for platforms in scout_data.values() for v in platforms.values())

    lines = [
        f"---",
        f"date: {now.strftime('%Y-%m-%d')}",
        f"type: trend_scout",
        f"total_items: {total}",
        f"---",
        "",
        f"# 选题调研报告 {now.strftime('%Y-%m-%d')}",
        "",
    ]

    if dry_run or not analysis:
        lines += [
            "## ⚠️ Dry-run 模式（未调用 LLM）",
            "",
            "## 原始采集数据",
            "",
            scout_text,
        ]
    else:
        lines += [
            "## AI 分析与选题建议",
            "",
            analysis,
            "",
            "---",
            "",
            "<details>",
            "<summary>原始采集数据（点击展开）</summary>",
            "",
            scout_text,
            "",
            "</details>",
        ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("报告已保存: %s", out_path)
    return out_path


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main(dry_run: bool = False, theme_ids: Optional[List[str]] = None) -> None:
    log.info("=" * 50)
    log.info("选题调研 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    topics = load_topics()
    published_titles = load_published_titles()
    all_themes = topics.get("themes", [])

    # 过滤主题
    if theme_ids:
        themes = [t for t in all_themes if t["id"] in theme_ids]
    else:
        themes = all_themes

    if not themes:
        log.error("没有可用的主题配置，退出")
        return

    log.info("调研 %d 个主题: %s", len(themes), ", ".join(t["name"] for t in themes))

    # 1. 多平台采集
    scout_data = run_scout(themes)
    scout_text = format_scout_data(scout_data, topics, published_titles)

    # 2. LLM 分析
    analysis = None
    if not dry_run:
        analysis = analyze_with_llm(scout_text, topics)
        if not analysis:
            log.warning("LLM 分析失败，仅保存原始数据")

    # 3. 保存 content_plan.json（供 research.py 消费）
    if analysis:
        save_content_plan(analysis, topics)

    # 4. 保存报告
    report_path = save_report(analysis, scout_text, scout_data, dry_run)

    total = sum(len(v) for platforms in scout_data.values() for v in platforms.values())
    log.info("完成：采集 %d 条素材，报告 → %s", total, report_path.name)
    log.info("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="小红书 Bot 选题调研")
    parser.add_argument("--dry-run", action="store_true",
                        help="只采集数据，不调用 LLM")
    parser.add_argument("--themes", nargs="+", metavar="THEME_ID",
                        help="只调研指定主题（如 greeks_explained strategy_playbook）")
    args = parser.parse_args()
    main(dry_run=args.dry_run, theme_ids=args.themes)
