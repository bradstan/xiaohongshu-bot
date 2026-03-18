#!/bin/bash
# 宇宙能量账号登录脚本（SS心灵疗愈所，端口 18061）
# 用法：bash browser-login.sh
# Chrome Profile: Profile 4（badstan）—— 专用于 SS心灵疗愈所
# 注意：wick123（期权账号）使用 Profile 5，见 ~/xiaohongshu-mcp/browser-login.sh

set -e

DIR="$HOME/xiaohongshu-bot/xhs-energy"
LOGIN_BIN="$DIR/xiaohongshu-login-darwin-arm64"
# 使用 Profile 4 专用 wrapper（固定 Chrome Profile，防止串号）
CHROME_WRAPPER="$DIR/chrome-wrapper-profile4.sh"

echo "🌐 启动浏览器登录 —— 【SS心灵疗愈所·宇宙能量】账号..."
echo "📌 Chrome 将以 Profile 4（badstan）打开，请登录【SS心灵疗愈所】（非 wick123！）"
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
echo "✅ 登录完成，正在重启 MCP server (port 18061)..."
bash "$DIR/start_mcp.sh"

echo "✅ MCP server 已重启，登录流程完成！"
echo ""
echo "🔍 打开登录页（强制退出旧 session），请重新扫码登录【SS心灵疗愈所】..."
open "https://creator.xiaohongshu.com/login?source=&redirectReason=401&lastUrl=%252Fnew%252Fhome"
