#!/usr/bin/env python3
"""
Track A curator.py — 每周精选期权教育素材

每周日 07:00 运行，从权威英文期权教育账号/平台采集高质量参考内容，
存入 state/curated/YYYY-WW-options.json，供 writer.py 深度改编使用。

和 research.py 的 collect_all() 区别：
- collect_all()：每篇文章临时采集，以关键词驱动，泛而快
- curator.py：每周精选，以教育账号为目标，深而准

典型用法：
  python pipeline/track_a/curator.py          # 采集本周素材
  python pipeline/track_a/curator.py --dry    # 只打印查询，不调用 agent-reach
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

# ─── 路径 ─────────────────────────────────────────────────────────────────────
import shutil as _shutil
# pipeline/track_a/ → pipeline/ → xhs-option/
SCRIPT_DIR   = Path(__file__).resolve().parent.parent.parent
CURATED_DIR  = SCRIPT_DIR / "state" / "curated"
LOG_FILE     = SCRIPT_DIR / "logs" / "curator_a.log"
# 优先从 PATH 查找 agent-reach，回退到常见安装位置
AGENT_REACH  = (
    _shutil.which("agent-reach") or
    str(Path.home() / ".local/bin/agent-reach")
)
AR_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:" + str(Path.home() / ".local/bin") + ":" + os.environ.get("PATH", ""),
}

sys.path.insert(0, str(SCRIPT_DIR))

# ─── 日志 ─────────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─── 权威期权教育账号的主题专项查询 ──────────────────────────────────────────
# 每个 theme_id 对应一批高信噪比查询：针对 tastytrade / OptionsAlpha 等教育账号
THEME_QUERIES = {
    "options_basics": [
        "tastytrade options basics beginner explained",
        "options alpha call put explained simply",
        "CBOE options education what is options contract",
        "options trading 101 strike price expiration premium",
        "beginner options trading rights obligation strike",
    ],
    "greeks_explained": [
        "tastytrade delta gamma theta vega explained",
        "options alpha delta options greek intuitive",
        "theta decay time value options explained daily",
        "implied volatility vega options greek intuitive",
        "gamma scalping options greek explained practical",
    ],
    "strategy_playbook": [
        "tastytrade covered call strategy explained",
        "options alpha iron condor setup step by step",
        "protective put hedge strategy options explained",
        "bull put spread credit spread options strategy",
        "straddle strangle options strategy when to use",
    ],
    "leaps_guide": [
        "tastytrade LEAPS long term options strategy",
        "LEAPS options vs stock leverage explained",
        "LEAPS options roll expiration management",
        "options alpha LEAPS deep ITM strategy",
        "LEAPS call options 1 year out strategy beginner",
    ],
    "risk_and_mindset": [
        "tastytrade position sizing options risk management",
        "options alpha win rate probability of profit",
        "options trading psychology loss discipline beginner",
        "max loss defined risk options trade sizing",
        "options trading common mistakes beginners avoid",
    ],
    "options_vs_stocks": [
        "options vs stock buying leverage comparison explained",
        "why buy options instead of stock capital efficiency",
        "options leverage risk reward vs owning shares",
        "options trading advantages over stocks explained",
        "buying call options vs stock capital efficiency",
    ],
    "earnings_and_events": [
        "tastytrade IV crush earnings options strategy",
        "implied volatility crush after earnings explained",
        "options earnings play straddle IV collapse",
        "tastytrade earnings options trade management",
        "selling options before earnings IV crush strategy",
    ],
}


# ─── agent-reach 工具 ─────────────────────────────────────────────────────────
def _ar_twitter(query: str, timeout: int = 30) -> List[dict]:
    """search-twitter，解析结果返回 list of dict。"""
    try:
        res = subprocess.run(
            [AGENT_REACH, "search-twitter", query],
            capture_output=True, text=True, timeout=timeout, env=AR_ENV,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return []
        return _parse_ar(res.stdout)
    except Exception as e:
        log.warning("search-twitter [%s] 失败: %s", query, e)
        return []


def _parse_ar(text: str) -> List[dict]:
    """解析 agent-reach 编号列表输出。"""
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
        items.append({
            "title": title,
            "url": url,
            "author": author,
            "engagement": engagement,
            "snippet": " ".join(extra),
        })
    return items


# ─── 评分 ─────────────────────────────────────────────────────────────────────
EDU_ACCOUNTS = {
    "tastytrade", "optionsalpha", "cboe", "tastyworks",
    "theotrade", "investwithrules", "optionseducation",
}

def _score_item(item: dict, theme_keywords: List[str]) -> float:
    """综合分：互动数 + 教育账号加权 + 关键词命中。"""
    score = min(item.get("engagement", 0) / 500.0, 2.0)  # 互动数归一化
    author_lower = item.get("author", "").lower().replace(" ", "").replace("_", "")
    for acc in EDU_ACCOUNTS:
        if acc in author_lower:
            score += 1.5
            break
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
    for kw in theme_keywords:
        if kw.lower() in text:
            score += 0.3
    return round(score, 3)


# ─── 采集单个主题 ─────────────────────────────────────────────────────────────
def curate_theme(theme_id: str, queries: List[str],
                 theme_keywords: List[str], top_n: int = 6,
                 dry: bool = False) -> List[dict]:
    """对一个主题执行所有查询，去重、评分、返回 top_n 条。"""
    seen: set = set()
    all_items: List[dict] = []

    for q in queries:
        if dry:
            log.info("  [dry] %s", q)
            continue
        log.info("  查询: %s", q)
        for item in _ar_twitter(q, timeout=30)[:5]:
            key = item["url"] or item["title"]
            if key and key not in seen:
                seen.add(key)
                item["query"] = q
                item["score"] = _score_item(item, theme_keywords)
                all_items.append(item)

    all_items.sort(key=lambda x: -x["score"])
    return all_items[:top_n]


# ─── 输出 ─────────────────────────────────────────────────────────────────────
def save_curated(curated: dict) -> Path:
    """
    写入 state/curated/YYYY-WW-options.json（机器读）
    + state/curated/YYYY-WW-options.md（人工阅读）
    """
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    week_str = today.strftime("%Y-W%V")

    json_path = CURATED_DIR / f"{week_str}-options.json"
    json_path.write_text(json.dumps(curated, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # 生成人类可读的 md
    md_lines = [
        f"# 期权教育素材精选 {week_str}",
        f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    for tid, items in curated.get("themes", {}).items():
        if not items:
            continue
        md_lines.append(f"## {tid}")
        for item in items:
            md_lines.append(f"- **{item['title'][:80]}** (score={item['score']})")
            if item.get("snippet"):
                md_lines.append(f"  > {item['snippet'][:150]}")
            if item.get("url"):
                md_lines.append(f"  🔗 {item['url']}")
        md_lines.append("")

    md_path = CURATED_DIR / f"{week_str}-options.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    log.info("已保存: %s + %s", json_path.name, md_path.name)
    return json_path


# ─── 外部接口：加载最新 curated 素材 ─────────────────────────────────────────
def load_latest_curated(theme_id: str, max_age_days: int = 7) -> str:
    """
    供 writer.py 调用。返回最新一周的精选素材文本（Markdown 格式）。
    若无有效文件或已过期则返回空字符串。
    """
    if not CURATED_DIR.exists():
        return ""
    json_files = sorted(CURATED_DIR.glob("*-options.json"), reverse=True)
    if not json_files:
        return ""

    try:
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        curated_date = datetime.strptime(data["date"], "%Y-%m-%d")
        if (datetime.now() - curated_date).days > max_age_days:
            return ""
        items = data.get("themes", {}).get(theme_id, [])
        if not items:
            return ""
        lines = [f"### 精选英文教育内容（来自权威期权教育账号，本周采集）"]
        for item in items:
            lines.append(f"- {item['title']}")
            if item.get("snippet"):
                lines.append(f"  摘要：{item['snippet'][:200]}")
        return "\n".join(lines)
    except Exception:
        return ""


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main(theme_ids: Optional[List[str]] = None, dry: bool = False) -> None:
    log.info("=" * 50)
    log.info("Track A 素材精选 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # 读取 topics.json 获取每个主题的 keywords
    topics_file = SCRIPT_DIR / "topics.json"
    topics_cfg: dict = {}
    if topics_file.exists():
        topics_cfg = json.loads(topics_file.read_text(encoding="utf-8"))
    keywords_map = {t["id"]: t.get("keywords", [])
                    for t in topics_cfg.get("themes", [])
                    if t.get("category") == "options"}

    queries_to_run = {tid: q for tid, q in THEME_QUERIES.items()
                      if not theme_ids or tid in theme_ids}

    curated: dict = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "themes": {},
    }

    total = 0
    for tid, queries in queries_to_run.items():
        log.info("精选主题: %s", tid)
        kw = keywords_map.get(tid, [])
        items = curate_theme(tid, queries, kw, top_n=6, dry=dry)
        curated["themes"][tid] = items
        total += len(items)
        log.info("  → %d 条", len(items))

    if not dry:
        save_curated(curated)

    log.info("完成：共精选 %d 条素材", total)
    log.info("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track A 期权教育素材精选")
    parser.add_argument("--theme", nargs="+", metavar="THEME_ID",
                        help="只采集指定主题（如 greeks_explained）")
    parser.add_argument("--dry", action="store_true",
                        help="只打印查询，不调用 agent-reach")
    args = parser.parse_args()
    main(theme_ids=args.theme, dry=args.dry)
