#!/bin/bash
# 定时任务入口：启动 MCP → 执行 feedback 脚本
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# 1. 确保 MCP server 运行
bash "$HOME/xiaohongshu-bot/xhs-option/start_mcp.sh"

# 2. 执行 feedback
/usr/bin/python3 "$HOME/xiaohongshu-bot/xhs-option/feedback.py"
