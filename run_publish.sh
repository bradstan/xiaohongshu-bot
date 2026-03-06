#!/bin/bash
# 定时任务入口：启动 MCP → 执行发布脚本
set -e

# 脚本所在目录（兼容 macOS 和 Linux）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PATH="/usr/local/bin:/usr/bin:$PATH"

# 1. 确保 MCP server 运行
bash "$SCRIPT_DIR/start_mcp.sh"

# 2. 执行发布（日志由 publish.py 自己的 FileHandler 管理，不再 >> 重定向）
python3 "$SCRIPT_DIR/publish.py"
