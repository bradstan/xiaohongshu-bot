#!/usr/bin/env python3
"""
NotebookLM → 知识库同步工具

用法：
  python3 notebooklm_sync.py              # 交互模式，逐主题引导
  python3 notebooklm_sync.py --list       # 列出知识库现状
  python3 notebooklm_sync.py --theme greeks_explained  # 只更新指定主题

流程：
  1. 脚本打开浏览器，跳转到 NotebookLM
  2. 对每个主题给出精确查询 prompt
  3. 你在 NotebookLM 问完后，把回答粘贴到终端
  4. 脚本自动保存到 knowledge_base/<theme_id>.md
"""

import argparse
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

KB_DIR = Path(__file__).parent / "knowledge_base"
KB_DIR.mkdir(exist_ok=True)

NOTEBOOKLM_URL = "https://notebooklm.google.com"

# ─── 每主题的 NotebookLM 查询 prompt ─────────────────────────────────────────
# 每个 prompt 设计为能从书籍中提取「深度可用」的知识，而非泛泛总结
THEME_QUERIES = {
    "options_basics": {
        "name": "期权基础",
        "query": (
            "请从书中总结以下内容，用中文回答，保留原书的具体例子和数字：\n"
            "1. 期权定义中最容易被误解的部分是什么？\n"
            "2. 买方和卖方在风险结构上的本质差异（原书是如何解释的）\n"
            "3. 时间价值损耗（Theta decay）的曲线特征，尤其是到期前最后30天\n"
            "4. 内在价值 vs 外在价值的计算方式，有无具体例题？\n"
            "5. 原书中有哪些关于散户常见亏损模式的论述？"
        ),
    },
    "greeks_explained": {
        "name": "Greeks 解析",
        "query": (
            "请从书中总结 Greeks 相关内容，用中文回答，保留原书观点和例子：\n"
            "1. Delta 的直觉理解：原书如何解释它不只是概率？\n"
            "2. Gamma 风险：什么情况下 Gamma 对散户最危险？\n"
            "3. Theta 衰减：原书有哪些具体数字说明到期前加速衰减？\n"
            "4. Vega 与 IV 的关系：原书如何建议在高/低 IV 环境下选策略？\n"
            "5. 实战中最重要的 Greeks 优先级排序（原书观点）"
        ),
    },
    "strategy_playbook": {
        "name": "策略手册",
        "query": (
            "请从书中总结期权策略内容，用中文回答，重点保留具体条件和数字：\n"
            "1. Covered Call：最佳执行条件、常见错误、盈利上限计算\n"
            "2. Cash Secured Put：与 Covered Call 的风险等价关系原书如何解释？\n"
            "3. Vertical Spread（牛市/熊市价差）：原书推荐的宽度/Delta 选择依据\n"
            "4. Iron Condor：原书建议的 IV Rank 阈值和 DTE 选择\n"
            "5. 选择策略的总体框架：市场方向 × IV 水平 × 时间维度"
        ),
    },
    "leaps_guide": {
        "name": "LEAPS 长期期权",
        "query": (
            "请从书中总结 LEAPS（1年以上期权）相关内容，用中文回答：\n"
            "1. LEAPS 替代持股的核心逻辑：资金效率如何计算？\n"
            "2. 执行价选择原则：原书推荐 Delta 范围是多少？为什么？\n"
            "3. LEAPS 的时间价值损耗特征与短期期权有何不同？\n"
            "4. Poor Man's Covered Call 策略：原书如何介绍？\n"
            "5. 持有 LEAPS 期间的风险管理：何时应该滚动合约？"
        ),
    },
    "risk_and_mindset": {
        "name": "风险与心态",
        "query": (
            "请从书中总结风险管理和交易心理相关内容，用中文回答：\n"
            "1. 仓位管理：原书推荐单笔期权占总资金的比例上限是多少？\n"
            "2. 最大亏损预设：原书有哪些具体的止损规则？\n"
            "3. 情绪化操作的典型场景：原书列举了哪些案例？\n"
            "4. 连续亏损后的资金管理：原书建议如何调整仓位规模？\n"
            "5. 原书中有无关于'赢家思维'vs'散户思维'的对比论述？"
        ),
    },
    "options_vs_stocks": {
        "name": "期权 vs 股票",
        "query": (
            "请从书中总结期权与股票对比的内容，用中文回答：\n"
            "1. 杠杆效应的真实数字：原书如何量化期权 vs 股票的杠杆比率？\n"
            "2. 非线性收益结构：原书如何解释这是期权的核心优势？\n"
            "3. 期权的资金效率：具体用同样资金期权能撬动多少股票价值？\n"
            "4. 什么情况下期权绝对优于持股？原书有哪些场景描述？\n"
            "5. 期权的隐性成本（买卖价差、流动性风险）原书如何警示？"
        ),
    },
    "earnings_and_events": {
        "name": "财报与事件驱动",
        "query": (
            "请从书中总结财报和事件驱动期权策略，用中文回答：\n"
            "1. IV Crush 机制：原书如何解释财报后 IV 暴跌？有具体数字吗？\n"
            "2. 财报前卖方策略：原书推荐在财报前多少天进场？\n"
            "3. Straddle vs Strangle：原书如何建议在事件前后使用？\n"
            "4. 历史波动率 vs 隐含波动率：如何判断 IV 是否被高估？\n"
            "5. 财报期权交易的常见陷阱：原书有哪些警告案例？"
        ),
    },
}


# ─── 工具函数 ─────────────────────────────────────────────────────────────────
def _open_browser(url: str) -> None:
    subprocess.Popen(["open", url])


def _read_multiline_paste(prompt_text: str) -> str:
    """读取多行粘贴内容，以 '---END---' 或连续两次回车结束。"""
    print(prompt_text)
    print("（粘贴完毕后，在新行输入 ---END--- 并回车）")
    lines = []
    empty_count = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "---END---":
            break
        if line.strip() == "":
            empty_count += 1
            if empty_count >= 2:
                break
        else:
            empty_count = 0
        lines.append(line)
    return "\n".join(lines).strip()


def _save_to_kb(theme_id: str, theme_name: str, content: str) -> None:
    path = KB_DIR / f"{theme_id}.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    # 保留文件头（# 标题行），替换正文
    header = f"# {theme_name} — 书籍精华笔记\n\n> 来源：NotebookLM 期权书籍笔记本\n> 最后更新：{datetime.now().strftime('%Y-%m-%d')}\n\n"
    path.write_text(header + content, encoding="utf-8")
    print(f"  ✓ 已保存 → knowledge_base/{theme_id}.md  ({len(content)} 字符)")


def _show_status() -> None:
    print("\n📚 知识库现状：")
    print(f"{'主题ID':<25} {'文件大小':>10}  {'状态'}")
    print("-" * 55)
    for tid, meta in THEME_QUERIES.items():
        path = KB_DIR / f"{tid}.md"
        if path.exists():
            size = path.stat().st_size
            # 简单判断：文件超过500字节才算"有实质内容"
            filled = "✓ 已填充" if size > 500 else "○ 仅模板"
            print(f"{tid:<25} {size:>8} B  {filled}  ({meta['name']})")
        else:
            print(f"{tid:<25} {'—':>10}  ✗ 缺失")
    print()


# ─── 主流程 ───────────────────────────────────────────────────────────────────
def sync_theme(theme_id: str) -> None:
    meta = THEME_QUERIES[theme_id]
    print(f"\n{'='*60}")
    print(f"  主题：{meta['name']}  ({theme_id})")
    print(f"{'='*60}")
    print("\n📋 请在 NotebookLM 中粘贴以下查询 prompt：\n")
    print("┌" + "─" * 58 + "┐")
    for line in meta["query"].split("\n"):
        print(f"│  {line:<56}│")
    print("└" + "─" * 58 + "┘")
    print()

    content = _read_multiline_paste("⬇️  将 NotebookLM 的回答粘贴到这里：")
    if not content:
        print("  ⚠️  内容为空，跳过保存。")
        return
    _save_to_kb(theme_id, meta["name"], content)


def main() -> None:
    parser = argparse.ArgumentParser(description="NotebookLM → 期权知识库同步")
    parser.add_argument("--list", action="store_true", help="显示知识库现状")
    parser.add_argument("--theme", type=str, help="只同步指定主题 ID")
    parser.add_argument("--all", action="store_true", help="同步所有主题（跳过已有内容）")
    args = parser.parse_args()

    if args.list:
        _show_status()
        return

    print("\n🚀 NotebookLM 知识库同步工具")
    print("   请确保已在浏览器中打开你的期权书籍笔记本\n")

    _open_browser(NOTEBOOKLM_URL)

    themes_to_sync = []
    if args.theme:
        if args.theme not in THEME_QUERIES:
            print(f"✗ 未知主题 ID: {args.theme}")
            print(f"  可用: {', '.join(THEME_QUERIES.keys())}")
            sys.exit(1)
        themes_to_sync = [args.theme]
    else:
        # 默认：优先处理未填充的主题
        _show_status()
        for tid in THEME_QUERIES:
            path = KB_DIR / f"{tid}.md"
            is_empty = not path.exists() or path.stat().st_size < 500
            if args.all or is_empty:
                themes_to_sync.append(tid)

        if not themes_to_sync:
            print("✅ 所有主题知识库已填充。如需强制更新，使用 --all 参数。")
            return

        print(f"待同步主题（{len(themes_to_sync)} 个）：")
        for tid in themes_to_sync:
            print(f"  • {tid}  ({THEME_QUERIES[tid]['name']})")
        print()
        input("准备好后按回车开始 → ")

    for tid in themes_to_sync:
        sync_theme(tid)
        if tid != themes_to_sync[-1]:
            cont = input("\n继续下一个主题？(回车继续 / q 退出) ").strip().lower()
            if cont == "q":
                break

    print("\n✅ 同步完成！运行以下命令确认知识库状态：")
    print("   python3 notebooklm_sync.py --list\n")


if __name__ == "__main__":
    main()
