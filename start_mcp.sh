#!/bin/bash
# 启动 xiaohongshu-mcp server（若未运行则启动）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 自动检测平台和架构
OS="$(uname -s)"
ARCH="$(uname -m)"

if [ "$OS" = "Darwin" ]; then
    if [ "$ARCH" = "arm64" ]; then
        MCP_BIN="$SCRIPT_DIR/xiaohongshu-mcp-darwin-arm64"
    else
        MCP_BIN="$SCRIPT_DIR/xiaohongshu-mcp-darwin-amd64"
    fi
elif [ "$OS" = "Linux" ]; then
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        MCP_BIN="$SCRIPT_DIR/xiaohongshu-mcp-linux-arm64"
    else
        MCP_BIN="$SCRIPT_DIR/xiaohongshu-mcp-linux-amd64"
    fi
else
    echo "Unsupported OS: $OS"
    exit 1
fi

LOG="$SCRIPT_DIR/mcp-server.log"
PID_FILE="$SCRIPT_DIR/mcp.pid"
PORT=18060

# 检查 MCP 二进制是否存在
if [ ! -f "$MCP_BIN" ]; then
    echo "$(date): ⚠ MCP server 二进制不存在: $MCP_BIN" >> "$LOG"
    echo "请将 xiaohongshu-mcp 二进制文件放置于 $SCRIPT_DIR/"
    exit 1
fi

# 检查是否已在运行且端口可达
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        # 进程活着，检查端口是否可达
        if command -v lsof >/dev/null 2>&1 && lsof -ti:"$PORT" >/dev/null 2>&1; then
            echo "$(date): MCP server 已在运行 (PID=$PID)" >> "$LOG"
            exit 0
        elif command -v ss >/dev/null 2>&1 && ss -tlnp | grep -q ":$PORT "; then
            echo "$(date): MCP server 已在运行 (PID=$PID)" >> "$LOG"
            exit 0
        fi
        # 进程活着但端口不可达，杀掉重启
        echo "$(date): MCP server 进程存活但不可达，强制重启" >> "$LOG"
        kill "$PID" 2>/dev/null
        sleep 2
        kill -9 "$PID" 2>/dev/null
    fi
fi

# 确保端口没被占用
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:"$PORT" | xargs kill -9 2>/dev/null || true
elif command -v fuser >/dev/null 2>&1; then
    fuser -k "$PORT"/tcp 2>/dev/null || true
fi
sleep 1

# 启动（必须在 SCRIPT_DIR 目录下运行，否则找不到 cookies.json）
echo "$(date): 启动 MCP server..." >> "$LOG"
cd "$SCRIPT_DIR" && "$MCP_BIN" -headless=true >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"
echo "$(date): MCP server 已启动 (PID=$(cat $PID_FILE))" >> "$LOG"

# 等待 server 就绪
sleep 5
