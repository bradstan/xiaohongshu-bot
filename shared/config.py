#!/usr/bin/env python3
"""
统一配置模块 — 路径全部动态推导，无硬编码用户名/主目录。

使用方法：
    from shared.config import PROJECT_ROOT, get_account, resolve_path

    # 获取 PROJECT_ROOT（monorepo 根目录）
    log_file = PROJECT_ROOT / "xhs-option/logs/feedback.log"

    # 获取账号配置（路径字段已自动解析为绝对路径）
    cfg = get_account("xhs-option")
    vault = Path(cfg["vault_pending"])
"""

import json
from pathlib import Path

# shared/ 的父目录即为 monorepo 根目录
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
ACCOUNTS_FILE = PROJECT_ROOT / "accounts.json"


def load_accounts() -> dict:
    """读取 accounts.json，返回原始 dict。"""
    return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))


def resolve_path(p: str) -> Path:
    """
    解析路径字段：
    - 以 "/" 开头 → 绝对路径（vault 外部目录等）
    - 其他         → 相对于 PROJECT_ROOT 解析
    """
    if p.startswith("/"):
        return Path(p)
    return PROJECT_ROOT / p


def get_account(account_id: str) -> dict:
    """
    获取账号配置，路径字段自动转换为绝对路径字符串。
    可安全传入 Path() 构造函数使用。
    """
    data = load_accounts()
    cfg  = dict(data["accounts"][account_id])
    for key in ("vault_pending", "vault_published", "publish_py",
                "state_file", "theme_weights_file", "python_bin"):
        if key in cfg:
            cfg[key] = str(resolve_path(cfg[key]))
    return cfg
