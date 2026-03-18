#!/usr/bin/env python3
"""
Track A（期权知识）生产脚本 — v2.0
1. 从 topics.json 选出 options 类主题
2. 多平台采集参考素材
3. 调用 track_a/writer.py 深度改编生成文章
4. 输出到 vault/待审核/，等待人工 approve 后移入 待发布/

Track B（AI工具）由独立的 scanner.py + translator.py 处理。
"""

import json
import os
import re
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# cron 环境没有用户 PATH，确保 Homebrew 路径可用（node/yt-dlp 等依赖）
if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

# ─── 配置 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent
TOPICS_FILE   = SCRIPT_DIR / "topics.json"
STATE_FILE    = SCRIPT_DIR / "published.json"
LOG_FILE      = SCRIPT_DIR / "research.log"
PUBLISH_DIR        = SCRIPT_DIR / "vault/待发布"
PUBLISHED_DIR      = SCRIPT_DIR / "vault/已发布"
REVIEW_DIR         = SCRIPT_DIR / "vault/待审核"
CONTENT_PLAN_FILE  = SCRIPT_DIR / "state" / "content_plan.json"
THEME_WEIGHTS_FILE = SCRIPT_DIR / "state" / "theme_weights.json"

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


# ─── 数据读取 ─────────────────────────────────────────────────────────────────
def load_topics() -> dict:
    with TOPICS_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"published": []}
    with STATE_FILE.open(encoding="utf-8") as f:
        return json.load(f)


# ─── 历史数据分析 ─────────────────────────────────────────────────────────────
def analyze_past_performance(state: dict) -> dict:
    """返回各已发文章的完整互动数据（含 theme_id、增长趋势）"""
    performance = {}
    for entry in state.get("published", []):
        cp = entry.get("checkpoints", {})
        # 取最新时间点数据
        latest = {}
        for label in ["14天", "7天", "3天", "24小时", "6小时", "3小时", "1小时", "30分钟"]:
            if label in cp:
                latest = cp[label]
                break
        if not latest:
            continue
        # 计算增长趋势（30min → latest）
        early = cp.get("30分钟", {})
        velocity = {
            "collected_growth": latest.get("collected", 0) - early.get("collected", 0),
            "liked_growth": latest.get("liked", 0) - early.get("liked", 0),
        }
        performance[entry.get("title", "")] = {
            "theme_id":  entry.get("theme_id", "unknown"),
            "collected": latest.get("collected", 0),
            "liked":     latest.get("liked", 0),
            "comment":   latest.get("comment", 0),
            "shared":    latest.get("shared", 0),
            "velocity":  velocity,
        }
    return performance


def load_latest_review() -> str:
    """读取已发布文章中的 AI 复盘内容，供 Claude 参考"""
    published_dir = PUBLISHED_DIR
    if not published_dir.exists():
        return ""
    insights = []
    for f in sorted(published_dir.glob("📊*.md"), reverse=True)[:3]:
        try:
            text = f.read_text(encoding="utf-8")
            m = re.search(r'> \*\*AI 复盘\*\*：(.+?)(?=\n<!-- /复盘数据 -->)', text, re.DOTALL)
            if m and "*(待分析...)*" not in m.group(1):
                title_m = re.search(r'^# (.+)$', text, re.MULTILINE)
                title = title_m.group(1) if title_m else f.stem
                insights.append(f"- 「{title}」：{m.group(1).strip()}")
        except Exception:
            pass
    return "\n".join(insights) if insights else ""


def get_published_titles(state: dict) -> List[str]:
    """获取所有已发布文章标题，用于去重"""
    titles = []
    for entry in state.get("published", []):
        if entry.get("title"):
            titles.append(entry["title"])
    return titles


def get_pending_titles() -> List[str]:
    """获取所有待发布文章标题（从文件名），用于关键词去重"""
    titles = []
    for f in PUBLISH_DIR.glob("*.md"):
        name = re.sub(r'^\d{4}-\d{2}-\d{2}[｜|]', '', f.stem)
        titles.append(name)
    return titles


def get_pending_theme_counts() -> dict:
    """
    统计「在途」主题数：待审核/ + 待发布/ 都算库存。
    Track A 文章写入 待审核/ 后即算入，避免重复生成同一主题。
    """
    counts: dict = {}
    for directory in (REVIEW_DIR, PUBLISH_DIR):
        for f in directory.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
                m = re.search(r'^theme_id:\s*(\S+)', text, re.MULTILINE)
                if m:
                    tid = m.group(1).strip()
                    counts[tid] = counts.get(tid, 0) + 1
            except Exception:
                pass
    return counts


def get_published_theme_counts() -> dict:
    """
    从已发布文章的 frontmatter 中读取 theme_id，精准统计已发各主题数量。
    替代原来不可靠的关键词匹配方案。
    """
    counts: dict = {}
    for f in PUBLISHED_DIR.glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
            m = re.search(r'^theme_id:\s*(\S+)', text, re.MULTILINE)
            if m:
                tid = m.group(1).strip()
                counts[tid] = counts.get(tid, 0) + 1
        except Exception:
            pass
    return counts


# ─── content_plan + 主题权重 读取 ────────────────────────────────────────────
def load_content_plan(max_age_days: int = 3) -> List[str]:
    """
    读取 trend_scout 输出的 content_plan.json，返回有序 theme_id 列表。
    超过 max_age_days 天则视为过期，返回空列表。
    """
    if not CONTENT_PLAN_FILE.exists():
        return []
    try:
        plan = json.loads(CONTENT_PLAN_FILE.read_text(encoding="utf-8"))
        plan_date = datetime.strptime(plan["date"], "%Y-%m-%d")
        if (datetime.now() - plan_date).days > max_age_days:
            log.info("content_plan.json 已过期（%s），忽略", plan["date"])
            return []
        ids = [s["theme_id"] for s in plan.get("suggested", [])]
        log.info("content_plan 有效（%s）：推荐主题 %s", plan["date"], ids)
        return ids
    except Exception as e:
        log.warning("读取 content_plan.json 失败: %s", e)
        return []


def load_theme_weights() -> dict:
    """读取 feedback.py 写入的主题权重，返回 {theme_id: float}。"""
    if not THEME_WEIGHTS_FILE.exists():
        return {}
    try:
        data = json.loads(THEME_WEIGHTS_FILE.read_text(encoding="utf-8"))
        return data.get("weights", {})
    except Exception:
        return {}


# ─── 多平台素材采集 ───────────────────────────────────────────────────────────
from collectors import collect_all, materials_to_prompt_text

# ─── Track A 写作器 ───────────────────────────────────────────────────────────
sys.path.insert(0, str(SCRIPT_DIR))
from pipeline.track_a.writer import write_article


# ─── 选题决策 ─────────────────────────────────────────────────────────────────
def pick_themes(topics_config: dict, performance: dict,
                notes_needed: int) -> List[dict]:
    """
    从主题池中选出本批要写的主题：
    - 优先选 content_plan.json 推荐的主题（trend_scout 输出，3天内有效）
    - 次优先按「库存最少」
    - 权重（theme_weights.json）打散同库存主题的顺序
    - 全程使用 frontmatter theme_id 精准统计
    """
    themes = topics_config.get("themes", [])
    if not themes:
        return []

    # ── 1. 外部信号：content_plan + 权重 ──
    plan_ids  = load_content_plan()       # trend_scout 推荐的顺序列表
    weights   = load_theme_weights()      # feedback 计算的主题得分

    # ── 2. 精准统计库存 ──
    pending_counts   = get_pending_theme_counts()
    published_counts = get_published_theme_counts()
    theme_counts = {t["id"]: published_counts.get(t["id"], 0) + pending_counts.get(t["id"], 0)
                   for t in themes}
    log.info("各主题库存（已发+待发）: %s",
             " | ".join(f"{tid}={cnt}" for tid, cnt in theme_counts.items() if cnt))

    # ── 3. 打分排序：库存低 + 计划推荐 + 权重高 → 排前面 ──
    plan_rank = {tid: i for i, tid in enumerate(plan_ids)}
    def _score(t: dict) -> tuple:
        tid = t["id"]
        cnt = theme_counts.get(tid, 0)
        # plan 推荐的主题：rank 越小越好；未推荐的 rank = 999
        plan = plan_rank.get(tid, 999)
        # 权重越高越好（取负使高权重排前）
        w = -weights.get(tid, 1.0)
        return (cnt, plan, w)

    sorted_themes = sorted(themes, key=_score)

    # ── 4. 按分类分组（保持类内顺序） ──
    by_category: dict = {}
    for t in sorted_themes:
        cat = t.get("category", "options")
        by_category.setdefault(cat, []).append(t)

    # ── 5. 均衡分配（50/50，奇数补到第一个分类） ──
    categories = list(by_category.keys())
    per_cat   = notes_needed // len(categories)
    remainder = notes_needed % len(categories)
    alloc = {c: per_cat + (1 if i < remainder else 0)
             for i, c in enumerate(categories)}

    # ── 6. 交替合并 ──
    pools = {c: by_category[c][:alloc[c]] for c in categories}
    result, seen = [], set()
    for i in range(max(alloc.values())):
        for c in categories:
            if i < len(pools[c]):
                t = pools[c][i]
                if t["id"] not in seen:
                    seen.add(t["id"])
                    result.append(t)

    return result[:notes_needed]



# ─── 主流程 ───────────────────────────────────────────────────────────────────
def main(force_count: int = None) -> None:
    log.info("=" * 50)
    log.info("Track A 内容生产 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    now = datetime.now()
    topics_config = load_topics()
    state = load_state()

    # 分析历史数据
    performance = analyze_past_performance(state)
    published_titles = get_published_titles(state)
    pending_titles = get_pending_titles()
    log.info("已发布 %d 篇，库存（待审核+待发布）%d 篇",
             len(published_titles), len(pending_titles))

    # 计算还需要生成几篇（按每日生成目标补足库存）
    if force_count:
        notes_needed = force_count
        log.info("强制生成 %d 篇（--count 参数）", notes_needed)
    else:
        generate_per_day = topics_config.get("generate_per_day", 5)
        notes_per_plan   = topics_config.get("notes_per_plan", 14)
        shortfall = max(0, notes_per_plan - len(pending_titles))
        notes_needed = min(shortfall, generate_per_day)
        if notes_needed == 0:
            log.info("库存充足（%d 篇），本次不生成新内容", len(pending_titles))
            return
    log.info("需要生成 %d 篇新内容", notes_needed)

    # 只选 options 类主题（ai_tools 由 Track B scanner+translator 处理）
    all_themes = pick_themes(topics_config, performance, notes_needed * 2)
    selected_themes = [t for t in all_themes
                       if t.get("category", "options") == "options"][:notes_needed]
    if not selected_themes:
        log.info("没有可用的 options 主题，退出")
        return
    log.info("选定 %d 个 options 主题: %s", len(selected_themes),
             ", ".join(t["name"] for t in selected_themes))

    # 读取差异化采集策略
    research_strategies = topics_config.get("research_strategies", {})

    # 逐主题：采集素材 → 调用 Track A writer → 写入待审核/
    generated = 0
    for theme in selected_themes:
        all_keywords  = theme.get("keywords", [])
        strategy      = research_strategies.get("options", {})
        source_limits = strategy.get("source_limits", {})
        source_order  = strategy.get("source_order", None)

        log.info("采集素材 [%s]（%d个关键词）", theme["name"], len(all_keywords))
        materials_by_source = collect_all(
            keywords=all_keywords,
            max_per_source=20,
            source_limits=source_limits,
        )
        ref_text = materials_to_prompt_text(
            materials_by_source,
            max_per_source=10,
            source_order=source_order,
        )

        result = write_article(theme, ref_text, performance, now)
        if result:
            generated += 1
        else:
            log.warning("文章生成失败: %s", theme["name"])

    log.info("=" * 50)
    log.info("本次生成 %d 篇文章，已放入待审核文件夹（等待人工 approve）", generated)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=0,
                        help="强制生成指定篇数（忽略库存检查）")
    args = parser.parse_args()
    main(force_count=args.count if args.count > 0 else None)
