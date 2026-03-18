#!/usr/bin/env python3
"""
共享互动数据反馈脚本（两账号合一）
- 每天凌晨 02:00 由 launchd 触发
- 遍历 xhs-option 和 xhs-energy 两个账号的 published.json
- 拉取各时间节点的点赞 / 收藏 / 评论 / 分享数
- 回写到 published.json checkpoints + Obsidian .md 文件
- 生成 perf.json（writer.py 注入历史表现用）
- 更新 theme_weights.json（research.py 选题权重用）

时间节点：30分钟 / 1小时 / 3小时 / 6小时 / 24小时 / 3天 / 7天 / 14天
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

# launchd 环境没有用户 PATH
if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/sbin:" + os.environ.get("PATH", "")

# ─── 账号配置（轻量账号体系的雏形）─────────────────────────────────────────────
ACCOUNTS = [
    {
        "id":           "xhs-option",
        "display_name": "wick123",
        "mcp_url":      "http://localhost:18060/mcp",
        "start_mcp_sh": "/Users/jarvis/xiaohongshu-bot/xhs-option/start_mcp.sh",
        "state_file":   "/Users/jarvis/xiaohongshu-bot/xhs-option/published.json",
        "topics_file":  "/Users/jarvis/xiaohongshu-bot/xhs-option/topics.json",
        "log_file":     "/Users/jarvis/xiaohongshu-bot/xhs-option/logs/feedback.log",
        "theme_weights_file": "/Users/jarvis/xiaohongshu-bot/xhs-option/state/theme_weights.json",
        "llm_dir":      "/Users/jarvis/xiaohongshu-bot/xhs-option",  # llm.py 所在目录
    },
    {
        "id":           "xhs-energy",
        "display_name": "SS心灵疗愈所",
        "mcp_url":      "http://localhost:18061/mcp",
        "start_mcp_sh": "/Users/jarvis/xiaohongshu-bot/xhs-energy/start_mcp.sh",
        "state_file":   "/Users/jarvis/xiaohongshu-bot/xhs-energy/published.json",
        "topics_file":  "/Users/jarvis/xiaohongshu-bot/xhs-energy/topics.json",
        "log_file":     "/Users/jarvis/xiaohongshu-bot/xhs-energy/logs/feedback.log",
        "theme_weights_file": "/Users/jarvis/xiaohongshu-bot/xhs-energy/state/theme_weights.json",
        "llm_dir":      "/Users/jarvis/xiaohongshu-bot/xhs-option",  # 共用同一个 llm.py
    },
]

# perf.json 输出路径（两账号共享，writer.py 读取时按 account_id 取对应 key）
PERF_FILE = Path("/Users/jarvis/xiaohongshu-bot/shared/perf.json")

# 时间节点：(分钟数, 标签)
CHECKPOINTS = [
    (30,    "30分钟"),
    (60,    "1小时"),
    (180,   "3小时"),
    (360,   "6小时"),
    (1440,  "24小时"),
    (4320,  "3天"),
    (10080, "7天"),
    (20160, "14天"),
]

# 得分公式（收藏权重最高，代表内容质量；评论/分享代表传播力）
def engagement_score(cp: dict) -> float:
    return (cp.get("collected", 0) * 3 +
            cp.get("liked",     0) * 1 +
            cp.get("comment",   0) * 2 +
            cp.get("shared",    0) * 2)

TRACKING_HEADER = "## 📊 发布数据追踪"
REVIEW_MARKER   = "<!-- 复盘数据 -->"
REVIEW_END      = "<!-- /复盘数据 -->"


# ─── 工具函数 ─────────────────────────────────────────────────────────────────
def setup_logger(log_file: str) -> logging.Logger:
    log = logging.getLogger(f"feedback.{log_file}")
    log.setLevel(logging.INFO)
    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(sh)
    return log


def latest_checkpoint(checkpoints: dict) -> dict:
    """取最新时间点的数据（按 CHECKPOINTS 倒序找）"""
    for _, label in reversed(CHECKPOINTS):
        if label in checkpoints:
            return checkpoints[label]
    return {}


# ─── 状态管理 ─────────────────────────────────────────────────────────────────
def load_state(state_file: str, topics_file: str) -> dict:
    path = Path(state_file)
    if not path.exists():
        return {"published": []}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)

    # 加载 topics 用于回填 theme_id
    topics_config = {}
    tp = Path(topics_file)
    if tp.exists():
        with tp.open(encoding="utf-8") as f:
            topics_config = json.load(f)

    entries = []
    for e in raw.get("published", []):
        if isinstance(e, str):
            e = {"file": e, "title": "", "published_at": "",
                 "feed_id": "", "xsec_token": "", "checkpoints": {}, "theme_id": "unknown"}
        if "checkpoints" not in e:
            e["checkpoints"] = {}
        if "theme_id" not in e or not e["theme_id"]:
            e["theme_id"] = _infer_theme_id(e.get("title", ""), topics_config)
        entries.append(e)
    raw["published"] = entries
    return raw


def save_state(state: dict, state_file: str) -> None:
    p = Path(state_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _infer_theme_id(title: str, topics_config: dict) -> str:
    for theme in topics_config.get("themes", []):
        for kw in theme.get("keywords", []):
            if kw.lower() in title.lower():
                return theme["id"]
    return "unknown"


# ─── MCP 调用（per-account session）────────────────────────────────────────────
def make_mcp_client(mcp_url: str, log: logging.Logger):
    """返回一个绑定 mcp_url 的 (get_session, call_tool) 闭包"""
    import urllib.request

    session_id: list[str] = [""]  # 用列表实现可变闭包变量

    MCP_ACCEPT = "application/json, text/event-stream"

    def get_session() -> str:
        if session_id[0]:
            return session_id[0]
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "feedback", "version": "2.0"},
            },
        }).encode()
        req = urllib.request.Request(
            mcp_url, data=payload,
            headers={"Content-Type": "application/json", "Accept": MCP_ACCEPT},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            sid = resp.headers.get("mcp-session-id", "")
            resp.read()
        if not sid:
            raise RuntimeError(f"MCP server {mcp_url} 未返回 session ID")
        session_id[0] = sid
        return sid

    def mcp_call(method: str, params: dict, req_id: int = 2) -> dict:
        sid = get_session()
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id,
                               "method": method, "params": params}).encode()
        req = urllib.request.Request(
            mcp_url, data=payload,
            headers={"Content-Type": "application/json", "Accept": MCP_ACCEPT,
                     "mcp-session-id": sid},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())

    def call_tool(tool_name: str, arguments: dict) -> dict:
        return mcp_call("tools/call", {"name": tool_name, "arguments": arguments})

    def check_alive() -> bool:
        try:
            get_session()
            return True
        except Exception as e:
            log.error("MCP 不可达 %s: %s", mcp_url, e)
            return False

    return call_tool, check_alive


# ─── 数据拉取 ─────────────────────────────────────────────────────────────────
def fetch_stats(feed_id: str, xsec_token: str,
                call_tool, log: logging.Logger) -> Optional[dict]:
    """调用 get_feed_detail，返回互动数据 dict 或 None"""
    try:
        result = call_tool("get_feed_detail", {"feed_id": feed_id, "xsec_token": xsec_token})
        if "error" in result:
            log.warning("get_feed_detail 错误: %s", result["error"])
            return None

        # 尝试多种返回格式
        interact = (
            result.get("data", {}).get("note", {}).get("interactInfo") or
            result.get("data", {}).get("interactInfo") or
            {}
        )
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

        def to_int(v) -> int:
            try:
                return int(str(v).replace(",", "").replace(".", ""))
            except Exception:
                return 0

        stats = {
            "liked":     to_int(interact.get("likedCount",     0)),
            "collected": to_int(interact.get("collectedCount", 0)),
            "comment":   to_int(interact.get("commentCount",   0)),
            "shared":    to_int(interact.get("sharedCount",    0)),
        }
        log.info("互动数据: 点赞%d 收藏%d 评论%d 分享%d",
                 stats["liked"], stats["collected"], stats["comment"], stats["shared"])
        return stats
    except Exception as e:
        log.warning("拉取互动数据失败: %s", e)
        return None


def retry_find_feed_id(entry: dict, call_tool,
                       log: logging.Logger) -> tuple[str, str]:
    """对 feed_id 为空的条目重新搜索（搜索 + 主页两种策略）"""
    title = entry.get("title", "")
    if not title:
        return "", ""

    clean_title = re.sub(r'\s+', '', title)

    def _match_feeds(feeds) -> tuple[str, str]:
        for feed in feeds:
            nc = feed.get("noteCard", {})
            dt = re.sub(r'\s+', '', nc.get("displayTitle", ""))
            if clean_title in dt or dt in clean_title:
                fid = feed.get("id", "")
                tok = feed.get("xsecToken", "")
                if fid:
                    return fid, tok
        return "", ""

    # 策略1: 关键词搜索
    try:
        result = call_tool("search_feeds", {"keyword": title[:10]})
        inner = result.get("result", {}).get("content", [])
        text = inner[0].get("text", "") if inner else ""
        feeds_data = json.loads(text) if text else {}
        feeds = feeds_data.get("feeds", []) or feeds_data.get("items", [])
        fid, tok = _match_feeds(feeds)
        if fid:
            log.info("搜索找到 feed_id: %s → %s", title[:15], fid)
            return fid, tok
    except Exception as e:
        log.warning("搜索 feed_id 失败: %s", e)

    # 策略2: 主页 list_feeds
    try:
        result = call_tool("list_feeds", {})
        inner = result.get("result", {}).get("content", [])
        text = inner[0].get("text", "") if inner else ""
        feeds_data = json.loads(text) if text else {}
        feeds = (feeds_data.get("feeds", []) or
                 feeds_data.get("items", []) or
                 (feeds_data if isinstance(feeds_data, list) else []))
        fid, tok = _match_feeds(feeds)
        if fid:
            log.info("主页匹配 feed_id: %s → %s", title[:15], fid)
            return fid, tok
    except Exception as e:
        log.warning("主页匹配 feed_id 失败: %s", e)

    return "", ""


# ─── 写回 Obsidian ─────────────────────────────────────────────────────────────
TABLE_HEADER = (
    "\n---\n"
    f"{TRACKING_HEADER}\n\n"
    "| 时间点 | 点赞 | 收藏 | 评论 | 分享 |\n"
    "|--------|------|------|------|------|\n"
)


def write_stats_to_md(md_path_str: str, label: str,
                      stats: dict, log: logging.Logger) -> None:
    md_path = Path(md_path_str)
    if not md_path.exists():
        log.warning("文件不存在，跳过: %s", md_path_str)
        return
    try:
        text = md_path.read_text(encoding="utf-8")
        new_row = (f"| {label} | {stats['liked']} | {stats['collected']} "
                   f"| {stats['comment']} | {stats['shared']} |")
        if TRACKING_HEADER in text:
            if f"| {label} |" in text:
                text = re.sub(rf'\| {re.escape(label)} \|[^\n]*', new_row, text)
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
        log.warning("无文件写入权限（macOS TCC），跳过: %s", md_path_str)
    except Exception as e:
        log.warning("写 md 失败: %s — %s", md_path_str, e)


# ─── AI 复盘（可选，仅在 llm.py 可用时触发）───────────────────────────────────
def _try_generate_analysis(entry: dict, llm_dir: str,
                           log: logging.Logger) -> None:
    """为单篇文章生成 AI 复盘（需要至少 6h 数据）"""
    md_path = Path(entry.get("file", ""))
    if not md_path.exists():
        return
    text = md_path.read_text(encoding="utf-8")
    if "*(待分析...)*" not in text:
        return

    cp = entry.get("checkpoints", {})
    if not any(label in cp for label in ["6小时", "24小时", "3天", "7天", "14天"]):
        return

    try:
        if llm_dir not in sys.path:
            sys.path.insert(0, llm_dir)
        from llm import call_llm  # type: ignore

        title = entry.get("title", "?")
        rows = []
        for _, label in CHECKPOINTS:
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
        analysis = analysis.strip().split("\n\n")[0].strip()
        if len(analysis) > 150:
            analysis = analysis[:147] + "..."
        text = text.replace("*(待分析...)*", analysis, 1)
        md_path.write_text(text, encoding="utf-8")

        # ✅ → 📊 重命名（已分析）
        new_name = md_path.name.replace("✅", "📊", 1)
        if new_name != md_path.name:
            new_path = md_path.parent / new_name
            md_path.rename(new_path)
            entry["file"] = str(new_path)
            log.info("复盘完成，已重命名: %s", new_name)
    except ImportError:
        log.debug("llm.py 不可用，跳过 AI 复盘")
    except Exception as e:
        log.warning("AI 复盘失败: %s", e)


# ─── theme_weights.json 更新 ──────────────────────────────────────────────────
def update_theme_weights(state: dict, weights_file: str,
                         log: logging.Logger) -> None:
    """
    根据各文章最新 checkpoint 计算主题得分，归一化写入 theme_weights.json。
    research.py / curator.py 的 pick_themes() 读取此文件。
    """
    theme_scores: dict[str, list[float]] = {}
    for entry in state.get("published", []):
        tid = entry.get("theme_id", "unknown")
        if tid == "unknown":
            continue
        latest = latest_checkpoint(entry.get("checkpoints", {}))
        if not latest:
            continue
        score = engagement_score(latest)
        theme_scores.setdefault(tid, []).append(score)

    if not theme_scores:
        return

    avg_scores = {tid: sum(s) / len(s) for tid, s in theme_scores.items()}
    max_s = max(avg_scores.values()) or 1.0
    weights = {tid: round(0.5 + (s / max_s) * 1.5, 3)
               for tid, s in avg_scores.items()}

    p = Path(weights_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"updated": datetime.now().strftime("%Y-%m-%d"),
                    "weights": weights}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    top3 = sorted(weights.items(), key=lambda x: -x[1])[:3]
    log.info("theme_weights 已更新: %s",
             " | ".join(f"{tid}={w}" for tid, w in top3))


# ─── perf.json（writer.py 消费格式）─────────────────────────────────────────
def _best_snapshot(entry: dict) -> Optional[dict]:
    """
    取最有代表性的快照数据：
    优先取 7天，其次 14天、3天、24小时、6小时。
    理由：7天数据最能反映笔记的综合传播效果（初始热度 + 搜索长尾）。
    """
    preferred = ["7天", "14天", "3天", "24小时", "6小时", "3小时"]
    cp = entry.get("checkpoints", {})
    for label in preferred:
        if label in cp:
            return {**cp[label], "snapshot_label": label}
    return None


def rebuild_perf_json(all_account_states: dict) -> None:
    """
    从所有账号的 published 数据生成 perf.json。
    格式：
    {
      "xhs-option": {
        "标题文字": {"collected": N, "liked": N, "theme_id": "...", "snapshot_label": "7天"},
        ...
      },
      "xhs-energy": { ... }
    }
    writer.py 调用时：
        perf = perf_data.get("xhs-option", {})
        # 按 collected 排序取 top3 / bottom3
    """
    perf: dict = {}
    for account_id, state in all_account_states.items():
        account_perf: dict = {}
        for entry in state.get("published", []):
            title = entry.get("title", "")
            if not title:
                continue
            snap = _best_snapshot(entry)
            if snap is None:
                continue
            account_perf[title] = {
                "collected":      snap.get("collected", 0),
                "liked":          snap.get("liked", 0),
                "comment":        snap.get("comment", 0),
                "theme_id":       entry.get("theme_id", "unknown"),
                "snapshot_label": snap.get("snapshot_label", "?"),
                "published_at":   entry.get("published_at", "")[:10],
            }
        perf[account_id] = account_perf

    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERF_FILE.write_text(
        json.dumps({"updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "accounts": perf}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 打印简单摘要
    for account_id, account_perf in perf.items():
        if not account_perf:
            continue
        sorted_p = sorted(account_perf.items(),
                          key=lambda x: x[1]["collected"], reverse=True)
        top = sorted_p[:3]
        print(f"  [{account_id}] top3 收藏: "
              + " / ".join(f"「{t[:10]}」{d['collected']}" for t, d in top))


# ─── 单账号主流程 ─────────────────────────────────────────────────────────────
def run_account(account: dict, now: datetime) -> dict:
    """处理单个账号，返回更新后的 state（供 perf.json 汇总用）"""
    log = setup_logger(account["log_file"])
    log.info("=" * 50)
    log.info("[%s] 互动数据检查 @ %s",
             account["id"], now.strftime("%Y-%m-%d %H:%M:%S"))

    # 确保 MCP server 运行
    try:
        subprocess.run(["/bin/bash", account["start_mcp_sh"]],
                       capture_output=True, timeout=30)
    except Exception as e:
        log.warning("启动 MCP 失败: %s", e)

    call_tool, check_alive = make_mcp_client(account["mcp_url"], log)
    if not check_alive():
        log.error("MCP 不可达，跳过 [%s]", account["id"])
        # 仍然返回现有 state（不中断 perf.json 生成）
        try:
            return load_state(account["state_file"], account["topics_file"])
        except Exception:
            return {"published": []}

    state = load_state(account["state_file"], account["topics_file"])
    changed = False

    for entry in state["published"]:
        if not entry.get("published_at"):
            continue
        try:
            pub_time = datetime.fromisoformat(entry["published_at"])
        except Exception:
            continue
        elapsed_minutes = (now - pub_time).total_seconds() / 60

        # 48h 内重试找 feed_id
        if not entry.get("feed_id") and elapsed_minutes < 2880:
            fid, tok = retry_find_feed_id(entry, call_tool, log)
            if fid:
                entry["feed_id"] = fid
                entry["xsec_token"] = tok
                changed = True

        if not entry.get("feed_id"):
            continue

        checkpoints_done = entry.get("checkpoints", {})
        for minutes, label in CHECKPOINTS:
            if label in checkpoints_done:
                continue
            if elapsed_minutes < minutes:
                continue
            log.info("拉取 [%s] %s 数据...", entry.get("title", "?")[:12], label)
            stats = fetch_stats(entry["feed_id"], entry.get("xsec_token", ""),
                                call_tool, log)
            if stats is not None:
                write_stats_to_md(entry["file"], label, stats, log)
                entry["checkpoints"][label] = {
                    **stats,
                    "fetched_at": now.isoformat(timespec="seconds"),
                }
                changed = True

    if changed:
        save_state(state, account["state_file"])
        log.info("状态已保存")
    else:
        log.info("无需更新")

    # AI 复盘（可选）
    review_changed = False
    for entry in state["published"]:
        if not entry.get("checkpoints"):
            continue
        old_file = entry.get("file", "")
        _try_generate_analysis(entry, account["llm_dir"], log)
        if entry.get("file", "") != old_file:
            review_changed = True
    if review_changed:
        save_state(state, account["state_file"])
        log.info("AI 复盘后状态已同步")

    # 更新 theme_weights
    update_theme_weights(state, account["theme_weights_file"], log)

    log.info("[%s] 完成", account["id"])
    return state


# ─── 入口 ─────────────────────────────────────────────────────────────────────
def main() -> None:
    now = datetime.now()
    print(f"[feedback] 开始 @ {now.strftime('%Y-%m-%d %H:%M:%S')}")

    all_states: dict = {}
    for account in ACCOUNTS:
        try:
            state = run_account(account, now)
            all_states[account["id"]] = state
        except Exception as e:
            print(f"[feedback] [{account['id']}] 意外错误: {e}")

    # 汇总生成 perf.json（两账号数据合并）
    print("[feedback] 生成 perf.json...")
    try:
        rebuild_perf_json(all_states)
        print(f"[feedback] perf.json 已写入: {PERF_FILE}")
    except Exception as e:
        print(f"[feedback] perf.json 生成失败: {e}")

    print(f"[feedback] 全部完成 @ {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
