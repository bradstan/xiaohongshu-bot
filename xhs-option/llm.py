"""
统一的 LLM 调用模块
使用 Claude CLI（OAuth 认证），自动从配置文件加载 token。

Token 来源优先级：
  1. CLAUDE_CODE_OAUTH_TOKEN 环境变量（Claude Desktop 注入）
  2. ~/.config/anthropic/oauth_token 文件（launchd 环境使用）
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("llm")

_OAUTH_TOKEN_FILE = Path.home() / ".config" / "anthropic" / "oauth_token"
# 优先从 PATH 查找 claude，回退到常见安装位置（不硬编码用户名）
_CLAUDE_BIN = (
    shutil.which("claude") or
    str(Path.home() / ".npm-global/bin/claude")
)


def _ensure_oauth_token() -> None:
    """确保 CLAUDE_CODE_OAUTH_TOKEN 环境变量存在（launchd 下从文件加载）"""
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
        return
    if _OAUTH_TOKEN_FILE.exists():
        token = _OAUTH_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
            log.info("已从配置文件加载 OAuth token")
            return
    log.warning("无 OAuth token（CLAUDE_CODE_OAUTH_TOKEN 未设置且 %s 不存在）", _OAUTH_TOKEN_FILE)


def call_llm(prompt: str, max_tokens: int = 4096, system: str = "") -> Optional[str]:
    """
    调用 Claude CLI 生成文本。
    launchd 环境下自动从配置文件加载 OAuth token。
    """
    _ensure_oauth_token()

    try:
        cmd = [_CLAUDE_BIN, "--print", "--max-turns", "1"]
        if system:
            cmd.extend(["--system-prompt", system])
        cmd.extend(["-p", prompt])

        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "")[:300]
            stdout = (result.stdout or "")[:300]
            log.warning("Claude CLI 非零退出 (%d): stderr=%s stdout=%s",
                        result.returncode, stderr, stdout)
            return None
        output = result.stdout.strip()
        if output:
            log.info("Claude CLI 成功 (%d 字符)", len(output))
            return output
        return None
    except subprocess.TimeoutExpired:
        log.warning("Claude CLI 超时 (180s)")
        return None
    except Exception as e:
        log.warning("Claude CLI 调用失败: %s", e)
        return None
