#!/usr/bin/env python3
"""
为已发布的 Obsidian note 重命名文件，在文件名前加 ✅ 前缀。
- 如果文件名已有 ✅ 则跳过
- 同步更新 published.json 里的路径
- 从 published.json 读取已发布文件列表
"""

import json
import re
import sys
from pathlib import Path

STATE_FILE = Path(__file__).parent / "published.json"
MARK_PREFIX = "✅"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"published": []}
    with STATE_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def mark_file(filepath: str) -> str:
    """
    重命名文件，文件名前加 ✅ 前缀。
    返回新文件路径（无论是否做了修改）。
    """
    path = Path(filepath)
    if not path.exists():
        print(f"  ⚠ 文件不存在: {filepath}")
        return filepath

    # 已有标记则跳过
    if path.name.startswith(MARK_PREFIX):
        print(f"  ✓ 已有标记，跳过: {path.name}")
        return filepath

    new_path = path.parent / f"{MARK_PREFIX}{path.name}"
    path.rename(new_path)
    print(f"  ✅ 已重命名: {path.name}")
    print(f"     → {new_path.name}")
    return str(new_path)


def main():
    state = load_state()
    entries = state.get("published", [])
    if not entries:
        print("published.json 中没有已发布文章")
        return

    print(f"共 {len(entries)} 篇已发布文章，开始标记...\n")
    changed = 0
    for entry in entries:
        if isinstance(entry, dict):
            old_path = entry.get("file", "")
            new_path = mark_file(old_path)
            if new_path != old_path:
                entry["file"] = new_path
                changed += 1
        elif isinstance(entry, str):
            mark_file(entry)

    if changed:
        save_state(state)
        print(f"\n完成：重命名了 {changed} 篇，已同步 published.json")
    else:
        print(f"\n完成：所有文件已有标记，无需修改")


if __name__ == "__main__":
    main()
