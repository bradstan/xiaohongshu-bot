#!/bin/bash
# 定时任务入口：启动 MCP → 执行发布脚本
set -e

LOG="$HOME/xiaohongshu-mcp/publish.log"
echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "$(date): 定时任务触发" >> "$LOG"

# 1. 确保 MCP server 运行
bash "$HOME/xiaohongshu-mcp/start_mcp.sh"

# 2. 执行发布
/usr/bin/python3 "$HOME/xiaohongshu-mcp/publish.py" >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date): 发布任务完成" >> "$LOG"
else
    echo "$(date): 发布任务失败 (exit=$EXIT_CODE)" >> "$LOG"
fi

# feedback.py 已由 launchd (com.jarvis.xhs-feedback) 每30分钟独立调度，无需在此重复执行

exit $EXIT_CODE
