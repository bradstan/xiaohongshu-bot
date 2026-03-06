#!/bin/bash
# 浏览器登录小红书（替代二维码登录）
# 用法：bash browser-login.sh
# 说明：小红书已更改登录流程，需要浏览器登录（可能需要扫码两次）

set -e

DIR="$HOME/xiaohongshu-mcp"
LOGIN_BIN="$DIR/xiaohongshu-login-darwin-arm64"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

echo "🌐 启动浏览器登录..."
echo "📌 请在弹出的 Chrome 窗口中完成小红书登录"
echo "   （如需扫码，可能需要扫两次）"
echo ""

# 备份旧 cookies
if [ -f "$DIR/cookies.json" ]; then
    cp "$DIR/cookies.json" "$DIR/cookies.json.bak"
    echo "🔒 已备份旧 cookies"
fi

# 启动浏览器登录（前台运行，完成后自动退出）
cd "$DIR"
"$LOGIN_BIN" -bin "$CHROME"

echo ""
echo "✅ 登录完成，正在重启 MCP server..."
bash "$DIR/start_mcp.sh"

echo "✅ MCP server 已重启，登录流程完成！"
