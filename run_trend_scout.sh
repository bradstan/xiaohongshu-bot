#!/bin/bash
# 定时任务入口：启动 MCP → 执行选题调研脚本
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:/Users/jarvis/.local/bin:$PATH"

# 1. 确保 MCP server 运行（小红书采集依赖）
bash "$HOME/xiaohongshu-mcp/start_mcp.sh"

# 2. 执行选题调研
/usr/bin/python3 "$HOME/xiaohongshu-mcp/trend_scout.py" "$@"
