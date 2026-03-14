#!/bin/bash
# 启动 xiaohongshu-mcp server（将宇宙能量账号，端口 18061）
MCP_BIN="$HOME/xiaohongshu-bot/xhs-energy/xiaohongshu-mcp-darwin-arm64"
LOG="$HOME/xiaohongshu-bot/xhs-energy/mcp-server.log"
PID_FILE="$HOME/xiaohongshu-bot/xhs-energy/mcp.pid"
PORT=18061

# 检查是否已在运行且端口可达
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
            echo "$(date): MCP server 已在运行 (PID=$PID)" >> "$LOG"
            exit 0
        fi
        echo "$(date): MCP server 进程存活但不可达，强制重启" >> "$LOG"
        kill "$PID" 2>/dev/null
        sleep 2
        kill -9 "$PID" 2>/dev/null
    fi
fi

# 确保端口没被占用
/usr/sbin/lsof -ti:"$PORT" | xargs kill -9 2>/dev/null
sleep 1

# 启动（必须在 xiaohongshu-yuzhou 目录下运行，否则找不到 cookies.json）
echo "$(date): 启动 MCP server (port $PORT)..." >> "$LOG"
cd "$HOME/xiaohongshu-bot/xhs-energy" && "$MCP_BIN" -port ":$PORT" -headless=true -bin "$HOME/xiaohongshu-bot/xhs-energy/chrome-wrapper.sh" >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"
echo "$(date): MCP server 已启动 (PID=$(cat $PID_FILE))" >> "$LOG"

sleep 5
