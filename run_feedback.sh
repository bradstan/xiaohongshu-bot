#!/bin/bash
# 定时任务入口：启动 MCP → 执行 feedback 脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PATH="/usr/local/bin:/usr/bin:$PATH"

# 1. 确保 MCP server 运行
bash "$SCRIPT_DIR/start_mcp.sh"

# 2. 执行 feedback
python3 "$SCRIPT_DIR/feedback.py"
