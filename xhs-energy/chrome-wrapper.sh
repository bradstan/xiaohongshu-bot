#!/bin/bash
# Chrome wrapper for 宇宙能量账号（SS心灵疗愈所）
# 完全独立的 user-data-dir，与期权账号物理隔离，永不串号
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --user-data-dir="$HOME/.chrome-yuzhou" \
    --ignore-certificate-errors \
    --no-first-run \
    --no-default-browser-check \
    "$@"
