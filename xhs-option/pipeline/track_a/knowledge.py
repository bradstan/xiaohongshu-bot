#!/usr/bin/env python3
"""
期权书籍知识库加载器

从 knowledge_base/<theme_id>.md 读取书籍精华，
注入 writer.py prompt 作为最高优先级内容参考。

知识库填充方式：
  1. 打开 NotebookLM，切换到期权书籍笔记本
  2. 针对每个主题提问，例如：
       "请总结 Options as a Strategic Investment 关于 covered call 的核心要点"
  3. 将回答整理后粘贴到对应 knowledge_base/<theme_id>.md
  4. 或直接运行 python notebooklm_sync.py 半自动同步
"""

from pathlib import Path

KB_DIR = Path(__file__).parent.parent.parent / "knowledge_base"


def load_theme_knowledge(theme_id: str) -> str:
    """
    加载指定主题的书籍知识摘要。
    文件不存在或为空时返回空字符串（不影响 pipeline 运行）。
    """
    path = KB_DIR / f"{theme_id}.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    return text if text else ""


def list_available() -> list[str]:
    """返回已有知识库文件的 theme_id 列表。"""
    return [p.stem for p in KB_DIR.glob("*.md") if p.stat().st_size > 100]
