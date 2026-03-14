#!/bin/bash
# 定时任务入口：启动 MCP → 执行发布脚本（将宇宙能量账号）
set -e

export PATH="/usr/sbin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# 1. 确保 MCP server 运行
bash "$HOME/xiaohongshu-bot/xhs-energy/start_mcp.sh"

# 2. 执行发布
"$HOME/xiaohongshu-bot/xhs-energy/venv/bin/python" "$HOME/xiaohongshu-bot/xhs-energy/publish.py"
