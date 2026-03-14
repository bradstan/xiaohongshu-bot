#!/usr/bin/env python3
"""
sync_cookies_from_chrome.py
将 Chrome 里的小红书 Cookie 同步到 cookies.json，延长 MCP server 登录状态。

原理：
  - 每次通过 browser-login.sh 登录后，cookies.json 包含最新 session
  - 用户在 Chrome（Profile 4）中正常浏览小红书时，Chrome 会刷新 token
  - 本脚本比较两者的 web_session 新鲜度，仅在 Chrome 有更新的 session 时才同步
  - 若 cookies.json 更新（如刚刚手动登录），则跳过同步，保留现有 cookies

建议每天运行一次（已配置 launchd job）。
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 优先用 pycookiecheat 所在的 venv（yuzhou/venv symlink 指向 wick123/venv）
# 用 try/import 方式 re-exec，避免 symlink 路径比较死循环
try:
    import pycookiecheat  # noqa: E402
except ImportError:
    _venv = Path("/Users/jarvis/xiaohongshu-mcp/venv/bin/python3")
    if _venv.exists():
        os.execv(str(_venv), [str(_venv)] + sys.argv)
    raise

SCRIPT_DIR   = Path("/Users/jarvis/xiaohongshu-bot/xhs-energy")
COOKIES_FILE = SCRIPT_DIR / "cookies.json"

# Chrome profile 路径（遍历所有 profile，找 web_session 最新的一个）
CHROME_BASE = Path("~/Library/Application Support/Google/Chrome").expanduser()
CANDIDATE_PROFILES = ["Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4", "Profile 5", "Profile 6"]

# 如果 cookies.json 在这个秒数内刚刚被写入（browser-login 后），跳过同步
SKIP_IF_COOKIES_NEWER_THAN = 12 * 3600  # 12 小时


def _find_best_profile() -> Path:
    """找 XHS web_session 最新（最近登录）的 Chrome profile。

    将宇宙能量账号用此脚本时，用户刚登录完，该 profile 的 web_session 最新，
    可以避免误抓 wick123 的 profile。
    """
    best, best_age = None, float("inf")
    for profile in CANDIDATE_PROFILES:
        db = CHROME_BASE / profile / "Cookies"
        if not db.exists():
            continue
        try:
            age = _get_chrome_web_session_age(db)
            if age < best_age:
                best, best_age = db, age
        except Exception:
            pass
    if best is None:
        raise FileNotFoundError("未找到含小红书 cookie 的 Chrome profile")
    print(f"  最新 web_session 在 {best.parent.name}，{best_age/60:.1f} 分钟前刚访问")
    return best


def _get_chrome_web_session_age(db_path: Path) -> float:
    """返回 Chrome 中 web_session cookie 的最后访问时间距今秒数（越小越新鲜）。"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp = f.name
        shutil.copy2(str(db_path), tmp)
        conn = sqlite3.connect(tmp)
        row = conn.execute(
            "SELECT last_access_utc FROM cookies WHERE name='web_session' LIMIT 1"
        ).fetchone()
        conn.close()
        os.unlink(tmp)
        if row and row[0]:
            # Chrome epoch → Unix epoch
            last_access_unix = row[0] / 1_000_000 - 11_644_473_600
            return time.time() - last_access_unix
    except Exception:
        pass
    return float("inf")  # unknown → treat as very old


def _get_metadata(db_path: Path) -> dict:
    """从 SQLite 读取 cookie 的元数据（domain/path/expires/httponly/secure）。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp = f.name
    try:
        shutil.copy2(str(db_path), tmp)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT name, host_key, path, expires_utc, is_httponly, is_secure
            FROM cookies
            WHERE host_key LIKE '%xiaohongshu.com'
            ORDER BY name
        """)
        rows = {row["name"]: dict(row) for row in cur.fetchall()}
        conn.close()
    finally:
        os.unlink(tmp)
    return rows


def get_xhs_cookies_from_chrome() -> list[dict]:
    """读取 Chrome 里所有小红书 cookies，返回与 cookies.json 格式一致的 list。"""
    db_path = _find_best_profile()
    print(f"  使用 profile: {db_path.parent.name}  ({db_path})")

    # pycookiecheat handles decryption correctly (v10 AES-CBC and newer AES-GCM)
    decrypted = pycookiecheat.chrome_cookies(
        "https://www.xiaohongshu.com",
        cookie_file=str(db_path),
    )
    print(f"  pycookiecheat 解密了 {len(decrypted)} 个 cookies")

    # Get metadata from SQLite
    metadata = _get_metadata(db_path)

    cookies = []
    for name, val in decrypted.items():
        if not val:
            continue
        meta = metadata.get(name, {})
        host_key  = meta.get("host_key", ".xiaohongshu.com")
        path      = meta.get("path", "/")
        httponly  = bool(meta.get("is_httponly", 0))
        secure    = bool(meta.get("is_secure", 0))

        # Chrome epoch (1601-01-01) → Unix epoch：差 11644473600 秒
        expires_utc  = meta.get("expires_utc") or 0
        expires_unix = int(expires_utc / 1_000_000 - 11_644_473_600) if expires_utc > 0 else -1

        cookies.append({
            "name":         name,
            "value":        val,
            "domain":       host_key,
            "path":         path,
            "expires":      expires_unix,
            "size":         len(name) + len(val),
            "httpOnly":     httponly,
            "secure":       secure,
            "session":      expires_unix < 0,
            "priority":     "Medium",
            "sameParty":    False,
            "sourceScheme": "Secure" if secure else "NonSecure",
            "sourcePort":   443 if secure else 80,
        })
    return cookies


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main() -> None:
    force = "--force" in sys.argv
    print("🔄 检查是否需要从 Chrome 同步小红书 Cookie..." + (" (--force 强制同步)" if force else ""))

    # 先找 Chrome 里最新的 XHS session
    try:
        db_path = _find_best_profile()
        chrome_age = _get_chrome_web_session_age(db_path)
        chrome_age_h = chrome_age / 3600
    except FileNotFoundError as e:
        print(f"⚠️  {e}，跳过同步")
        return

    # 判断是否需要同步：
    # - cookies.json 不存在或为空 → 强制同步
    # - Chrome session 比 cookies.json 更新（chrome_age < cookies.json mtime 距今）→ 同步
    # - cookies.json 比 Chrome 更新且不超过 12h → 跳过（已有更新鲜的 session）
    cookies_mtime_age = (time.time() - COOKIES_FILE.stat().st_mtime) / 3600 if COOKIES_FILE.exists() else float("inf")

    existing_valid = False
    if COOKIES_FILE.exists():
        try:
            existing_valid = bool(json.loads(COOKIES_FILE.read_text()))
        except Exception:
            pass

    print(f"  cookies.json 年龄：{cookies_mtime_age:.1f}h，Chrome web_session 年龄：{chrome_age_h:.1f}h")

    if not force:
        if existing_valid and chrome_age_h > cookies_mtime_age * 1.1:
            # Chrome session 比 cookies.json 更旧，无需同步
            print(f"⏭️  Chrome cookies ({chrome_age_h:.1f}h) 比现有 cookies.json ({cookies_mtime_age:.1f}h) 更旧，跳过同步")
            return

        if existing_valid and chrome_age_h <= cookies_mtime_age and cookies_mtime_age < SKIP_IF_COOKIES_NEWER_THAN / 3600:
            # cookies.json 比 Chrome 更新，且不超过 12h → 已是最新 session，跳过
            print(f"⏭️  cookies.json ({cookies_mtime_age:.1f}h) 比 Chrome ({chrome_age_h:.1f}h) 更新，无需同步")
            return

    print("🔄 从 Chrome 同步小红书 Cookie...")
    cookies = get_xhs_cookies_from_chrome()
    if not cookies:
        print("❌ 未找到小红书 cookies，请先在 Chrome 中登录小红书")
        sys.exit(1)

    # 备份旧 cookies
    if COOKIES_FILE.exists():
        shutil.copy2(str(COOKIES_FILE), str(COOKIES_FILE.with_suffix(".json.bak")))

    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False)
    print(f"✅ 同步完成：{len(cookies)} 条 cookies → {COOKIES_FILE}")

    # 重启 MCP server（yuzhou，port 18061）以加载新 cookies
    print("🔄 重启 MCP server (port 18061)...")
    subprocess.run(["bash", str(SCRIPT_DIR / "start_mcp.sh")], check=False)
    print("✅ MCP server 已重启，新 cookie 已生效")


if __name__ == "__main__":
    main()
