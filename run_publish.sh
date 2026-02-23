#!/bin/bash
# 定时任务入口：启动 MCP → 执行发布脚本
set -e

# launchd/cron 环境没有用户 PATH，手动补上 Homebrew（node/yt-dlp 等依赖）
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# 1. 确保 MCP server 运行
bash "$HOME/xiaohongshu-mcp/start_mcp.sh"

# 2. 执行发布（日志由 publish.py 自己的 FileHandler 管理，不再 >> 重定向）
/usr/bin/python3 "$HOME/xiaohongshu-mcp/publish.py"
