#!/bin/bash
# 启动 xiaohongshu-mcp server（若未运行则启动）
MCP_BIN="$HOME/xiaohongshu-bot/xhs-option/xiaohongshu-mcp-darwin-arm64"
LOG="$HOME/xiaohongshu-bot/xhs-option/mcp-server.log"
PID_FILE="$HOME/xiaohongshu-bot/xhs-option/mcp.pid"
PORT=18060

# 端口已可达则直接退出（兼容 launchd 管理的进程，不依赖 pid 文件）
if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
    echo "$(date): MCP server 已在运行 (port $PORT 可达)" >> "$LOG"
    exit 0
fi

# 检查是否已在运行且端口可达
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        # 进程活着，检查端口是否可达（用 nc，不依赖 lsof）
        if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
            echo "$(date): MCP server 已在运行 (PID=$PID)" >> "$LOG"
            exit 0
        fi
        # 进程活着但端口不可达（浏览器 context 可能已坏），杀掉重启
        echo "$(date): MCP server 进程存活但不可达，强制重启" >> "$LOG"
        kill "$PID" 2>/dev/null
        sleep 2
        kill -9 "$PID" 2>/dev/null
    fi
fi

# 确保端口没被占用（用完整路径 /usr/sbin/lsof，兼容 launchd 受限 PATH）
/usr/sbin/lsof -ti:"$PORT" | xargs kill -9 2>/dev/null
sleep 1

# 启动（必须在 xiaohongshu-mcp 目录下运行，否则找不到 cookies.json）
echo "$(date): 启动 MCP server..." >> "$LOG"
cd "$HOME/xiaohongshu-bot/xhs-option" && "$MCP_BIN" -headless=true -bin "$HOME/xiaohongshu-bot/xhs-option/chrome-wrapper.sh" >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"
echo "$(date): MCP server 已启动 (PID=$(cat $PID_FILE))" >> "$LOG"

# 等待 server 就绪
sleep 5
