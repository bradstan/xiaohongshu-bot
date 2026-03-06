#!/usr/bin/env python3
"""
Track A 期权知识深度改编写作器
输入：主题配置 + 多平台素材
输出：一篇自然、深度、有中文腔调的期权知识文章 → vault/待审核/（等人工 approve）

核心理念：
- 素材是知识来源，不是要翻译的原文
- Claude 用素材理解概念，然后用自己的话讲出来
- 文章应该读起来像一个懂期权的朋友在聊天，而不是教科书或PPT
"""

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR  = Path("/Users/jarvis/xiaohongshu-mcp")
REVIEW_DIR  = Path("/Users/jarvis/xiaohongshu-mcp/vault/待发布")
LOG_FILE    = SCRIPT_DIR / "logs" / "writer_a.log"

sys.path.insert(0, str(SCRIPT_DIR))
from llm import call_llm
from pipeline.track_a.curator import load_latest_curated
from pipeline.track_a.knowledge import load_theme_knowledge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

MAX_CHARS = 1000   # 宽松上限，正文应自然在 400-600 字落地


# ─── QA ──────────────────────────────────────────────────────────────────────
def _qa_check(article: str) -> tuple[bool, str]:
    body = re.sub(r'^---\n.*?\n---\n', '', article, count=1, flags=re.DOTALL)
    body = re.sub(r'^#\s+.+\n', '', body, count=1, flags=re.MULTILINE)
    body = re.sub(r'^#[\w\u4e00-\u9fff#\s]+$', '', body, flags=re.MULTILINE)
    body = re.sub(r'^---+$', '', body, flags=re.MULTILINE)
    body = re.sub(r'^⚠️.*$', '', body, flags=re.MULTILINE)
    char_count = len(re.sub(r'\s+', '', body))

    if char_count < 150:
        return False, f"正文过短（{char_count}字）"
    if char_count > MAX_CHARS:
        return False, f"正文超限（{char_count}字）"
    if not re.search(r'^#\s+.+', article, re.MULTILINE):
        return False, "缺少标题行"

    # 检测过度结构化（连续3个以上 ## 段落 = AI腔报警）
    h2_count = len(re.findall(r'^##\s+', article, re.MULTILINE))
    if h2_count >= 3:
        return False, f"结构过碎（{h2_count}个二级标题，上限2个）"

    return True, "OK"


# ─── 知识库 & 精选素材加载 ────────────────────────────────────────────────────
def _get_knowledge_section(theme_id: str) -> str:
    """加载 NotebookLM 书籍精华。有内容时作为最高权威注入 prompt。"""
    kb = load_theme_knowledge(theme_id)
    if not kb:
        return ""
    return (
        "\n### 📚 期权经典书籍精华（最高权威来源，优先于其他素材）\n"
        "以下内容来自经典期权书籍，代表业界最成熟的理论与实战体系。\n"
        "**必须**从中汲取深度观点，融入文章论证，让内容有书卷底气。\n\n"
        f"{kb}\n"
    )


def _get_curated_section(theme_id: str) -> str:
    """加载本周精选素材，生成 prompt 嵌入段。无数据时返回空字符串。"""
    curated = load_latest_curated(theme_id)
    if not curated:
        return ""
    return f"\n### 本周权威渠道精选（质量高于普通搜索，优先参考）\n{curated}\n"


# ─── Prompt ──────────────────────────────────────────────────────────────────
def build_prompt(theme: dict, ref_text: str,
                 performance: dict, now: datetime) -> str:

    # 历史表现摘要（只取最有参考价值的部分）
    perf_lines = []
    if performance:
        sorted_p = sorted(performance.items(),
                          key=lambda x: x[1]["collected"], reverse=True)
        for title, d in sorted_p[:3]:
            perf_lines.append(
                f"- 「{title}」收藏 {d['collected']}，点赞 {d['liked']}")
        bottom = sorted_p[-2:] if len(sorted_p) > 3 else []
        if bottom:
            perf_lines.append("表现较差（避开类似方向）：")
            for title, d in bottom:
                perf_lines.append(f"  - 「{title}」收藏 {d['collected']}")

    perf_section = "\n".join(perf_lines) if perf_lines else "（暂无历史数据）"

    keywords_str = "、".join(theme.get("keywords", [])[:5])

    return f"""你是一个真实的美股期权玩家，在小红书上分享自己的期权认知。

你写文章的风格是：像一个懂行的朋友在咖啡馆跟你解释一个容易踩坑的概念。
你不是老师，不是分析师，不是在写报告——你是在聊天。

## 本篇要讲的概念
主题：{theme['name']}
核心说明：{theme['description']}
涉及关键词：{keywords_str}

{_get_knowledge_section(theme['id'])}
## 参考素材
以下是从多个平台收集的相关内容。
**你的任务是从中吸收知识，然后用自己的话讲出来，绝不是翻译或总结这些素材。**

{ref_text if ref_text.strip() else "（无外部素材，基于你的期权知识创作）"}

{_get_curated_section(theme['id'])}

## 历史表现参考
{perf_section}

---

## ⚠️ 写作红线（违反 = 废稿）

### 格式红线
- 正文必须包含 **1-2段 bullet points**（`-` 开头的列表），用于列举并列要点（如对比项、判断标准、操作步骤）；列表前后必须有散文句子承接
- 禁止使用 **3个或以上** 的 `## 二级标题` 分割文章
- 禁止以 bullet list 作为文章主体（散文段落仍须占主导）
- 禁止连续超过4个独立短句段落（会产生碎片感）

### 内容红线
- 禁止引用任何真实市场数据（股价、涨跌幅、财报数字）
- 禁止写"我买了/卖了/持有"等第一人称交易描述
- 禁止给出具体买卖建议

### 语言红线
这些词一出现就是 AI 腔，禁止使用：
"简单来说"、"值得注意的是"、"总的来说"、"首先…其次…最后"、
"不得不说"、"可以帮助你"、"让我们来看看"、"相信很多人"

---

## ✅ 你应该写成这样

举例（这只是风格示范，不是让你照抄）：

> 很多人第一次买期权亏钱，亏得莫名其妙。
> 方向没错——股票确实涨了——但期权反而跌了。
>
> 原因几乎都是这个：0.2 Delta 的虚值期权，
> 股票涨5%，期权可能只涨了3%甚至不涨。
> Delta 不是在告诉你期权值多少，
> 而是在告诉你，你的仓位对涨跌有多敏感。
>
> 新手喜欢买虚值，因为便宜，感觉杠杆大。
> 但 Delta 0.2 意味着股票要涨 5% 你才能感受到 1% 的变动。
> 很多时候涨了，你还没等到回本就到期了。

注意：这段话没有任何标题，没有任何列表，逻辑是自然流动的。

---

## 输出格式（严格遵守）

```
---
tags: [投资]
date: {now.strftime('%Y-%m-%d')}
version: v1.0
category: options
theme_id: {theme['id']}
---

# 标题（20字以内）

正文（自然段落，400-600字）

---

#期权 #美股期权 #（其他6-8个相关标签）

⚠️ 仅为知识分享，不构成投资建议。
```

直接输出文章内容，不要有任何额外说明或前言。
"""


# ─── AI工具 Prompt ────────────────────────────────────────────────────────────
def build_prompt_ai_tools(theme: dict, ref_text: str,
                          performance: dict, now: datetime) -> str:
    """
    AI工具主题专属 Prompt — 实操清单型。
    核心标准：读完立刻知道今天可以去试什么。
    """
    perf_lines = []
    if performance:
        sorted_p = sorted(performance.items(),
                          key=lambda x: x[1]["collected"], reverse=True)
        for title, d in sorted_p[:3]:
            perf_lines.append(
                f"- 「{title}」收藏 {d['collected']}，点赞 {d['liked']}")
    perf_section = "\n".join(perf_lines) if perf_lines else "（暂无历史数据）"
    keywords_str = "、".join(theme.get("keywords", [])[:5])

    return f"""你是一个深度使用 AI 工具的人，在小红书写给同样爱折腾工具的读者。

读完你的文章，读者应该立刻知道"我今天回去可以试什么"。
不需要哲学，不需要感悟，需要的是**具体可操作的技巧或方法**。

## 本篇主题
{theme['name']} — {theme['description']}
关键词：{keywords_str}

## 参考素材
{ref_text if ref_text.strip() else "（无外部素材，基于工具本身的真实功能写作）"}

## 历史表现
{perf_section}

---

## 文章模板（必须从以下3种选1）

### 模板①「X个高级用法 / X个你不知道的技巧」
列出3-5个具体用法，每个用法包含：
  - 这个用法叫什么 / 怎么触发
  - 解决什么具体问题
  - 一句话说明为什么大多数人不知道或没用起来

标题示例：
  ✓ "Obsidian 4个用了才知道的隐藏技巧"
  ✓ "NotebookLM 3个高级用法，大多数人只用到了第1个"
  ✗ "Obsidian使用心得"

### 模板②「必装/必用的X个[插件/功能/设置]」
围绕一个场景（如：读书笔记、项目管理、每日记录），推荐3-5个具体插件或设置，每个说明：
  - 名称（必须是真实存在的）
  - 装了之后能做到什么（之前做不到的）
  - 适合谁用

标题示例：
  ✓ "Obsidian做读书笔记必装的4个插件"
  ✓ "Claude Code必知的3个MCP工具，接上去能力直接翻倍"
  ✗ "Obsidian插件推荐"

### 模板③「一文讲透：[具体功能] 从零到能用」
只讲一个功能，但讲透。结构：
  1. 这个功能是干什么的（1-2句，不展开）
  2. 大多数人卡在哪一步（点出真实痛点）
  3. 正确的使用方法，步骤清晰（这是重点，篇幅最长）
  4. 一个实际场景举例

标题示例：
  ✓ "NotebookLM的Audio Overview怎么用？一文讲透"
  ✓ "Claude Code的CLAUDE.md是什么？配置好了效率差一个量级"
  ✗ "Claude Code功能介绍"

---

## 写作要求

**每个技巧/插件/步骤必须具体**：
- 写出名称、触发方式、或操作路径（比如"设置→外观→字体"）
- 不能只说"有个功能很好用"，要说"这个功能叫XXX，用来做YYY"
- 场景举例必须是真实可能发生的，不要抽象比喻

**真实性红线**（违反 = 废稿）：
- 插件/功能名称必须真实存在，不得捏造
- 禁止写"经我实测"等无来源的个人体验
- 禁止承诺截图、视频、或附件

**结构要求**：
- 每篇必须有 **1-2段 bullet points**，用来列举技巧/插件/步骤条目
- 每个 bullet 条目后面必须有1-2句解释，不能只是名字
- 禁止超过2个 `##` 二级标题（保持轻量，不要做成目录）
- 禁用套话："简单来说"、"总的来说"、"不得不说"、"相信很多人"、"可以帮助你"

---

## 输出格式（严格遵守）

```
---
tags: [AI工具]
date: {now.strftime('%Y-%m-%d')}
version: v1.0
category: ai_tools
theme_id: {theme['id']}
template: （填写选用的模板编号，如 ①/②/③）
---

# 标题（含数字或"一文讲透"，20字以内）

开场白（1-2句，直接点明读者会得到什么，不废话）

[核心内容：3-5个技巧/插件/步骤，用 bullet points 列举，每条附解释]

收尾（1句，说清楚适用场景或下一步行动）

---

#标签1 #标签2 #标签3 #标签4 #标签5 #标签6 #标签7

⚠️ 仅为工具分享，效果因人因场景而异。
```

直接输出文章，不要有任何前言或说明。
"""


# ─── 主函数 ───────────────────────────────────────────────────────────────────
def write_article(theme: dict, ref_text: str,
                  performance: dict, now: datetime) -> Optional[dict]:
    """生成一篇 Track A 文章，输出到 待审核/。返回文章信息或 None。"""

    category = theme.get("category", "options")
    if category == "ai_tools":
        prompt = build_prompt_ai_tools(theme, ref_text, performance, now)
        log.info("生成 AI工具 文章: %s", theme["name"])
    else:
        prompt = build_prompt(theme, ref_text, performance, now)
        log.info("生成期权文章: %s", theme["name"])

    article = call_llm(prompt, max_tokens=3000)
    if not article:
        log.warning("LLM 返回为空: %s", theme["name"])
        return None

    ok, reason = _qa_check(article)
    if not ok:
        log.warning("QA 不通过（%s），尝试修复...", reason)
        fix_prompt = f"""以下文章有问题：{reason}

请在保持内容和格式不变的前提下修复：
- 如果标题过多（≥3个##）：合并段落，改成自然流动的散文
- 如果正文过长：删减次要内容，保留最核心的一个概念
- 不要重新创作，只做必要的结构调整

直接输出修复后的完整文章。

{article}"""
        article = call_llm(fix_prompt, max_tokens=3000) or article
        ok, reason = _qa_check(article)
        if not ok:
            log.warning("修复后仍不通过（%s）: %s", reason, theme["name"])
            return None

    # 确保 frontmatter 含 theme_id（writer prompt 已要求，这里做兜底）
    if "theme_id:" not in article:
        article = re.sub(
            r'^(---\ntags:.*?\ncategory:\s*(?:options|ai_tools))',
            rf'\1\ntheme_id: {theme["id"]}',
            article, count=1, flags=re.DOTALL,
        )

    title_m = re.search(r'^#\s+(.+)$', article, re.MULTILINE)
    if not title_m:
        log.warning("无法提取标题: %s", theme["name"])
        return None

    raw_title  = title_m.group(1).strip()
    safe_title = re.sub(r'[/\\:*?"<>|]', '', raw_title)
    safe_title = re.sub(r'\s+', '', safe_title)[:30]
    filename   = f"{now.strftime('%Y-%m-%d')}｜{safe_title}.md"

    # 写入 待审核/
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REVIEW_DIR / filename
    out_path.write_text(article, encoding="utf-8")
    log.info("✓ 已写入待审核: %s", filename)

    return {
        "title":    raw_title,
        "content":  article,
        "filename": filename,
        "theme_id": theme["id"],
    }
