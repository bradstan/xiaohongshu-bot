#!/bin/bash
# 期权账号登录脚本（wick123，端口 18060）
# 用法：bash browser-login.sh
# Chrome Profile: Profile 5 —— 专用于 wick123
# 注意：SS心灵疗愈所（宇宙能量账号）使用 Profile 4，见 ~/xiaohongshu-yuzhou/browser-login.sh

set -e

DIR="$HOME/xiaohongshu-bot/xhs-option"
LOGIN_BIN="$DIR/xiaohongshu-login-darwin-arm64"
# 使用 Profile 5 专用 wrapper（固定 Chrome Profile，防止串号）
CHROME_WRAPPER="$DIR/chrome-wrapper-profile5.sh"

echo "🌐 启动浏览器登录 —— 【wick123·期权】账号..."
echo "📌 Chrome 将以 Profile 5 打开，请登录【wick123】（非 SS心灵疗愈所！）"
echo "   （如需扫码，可能需要扫两次）"
echo ""

# 备份旧 cookies
if [ -f "$DIR/cookies.json" ]; then
    cp "$DIR/cookies.json" "$DIR/cookies.json.bak"
    echo "🔒 已备份旧 cookies"
fi

# 启动浏览器登录（前台运行，完成后自动退出）
cd "$DIR"
"$LOGIN_BIN" -bin "$CHROME_WRAPPER"

echo ""
echo "✅ 登录完成，正在重启 MCP server..."
bash "$DIR/start_mcp.sh"

echo "✅ MCP server 已重启，登录流程完成！"
