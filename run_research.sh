#!/bin/bash
# 定时任务入口：启动 MCP → 执行 research 脚本
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# 1. 确保 MCP server 运行
bash "$HOME/xiaohongshu-mcp/start_mcp.sh"

# 2. 执行 research
/usr/bin/python3 "$HOME/xiaohongshu-mcp/research.py" "$@"
