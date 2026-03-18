#!/bin/bash
# Chrome wrapper for 期权账号（wick123）
# 完全独立的 user-data-dir，与宇宙能量账号物理隔离，永不串号
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --user-data-dir="$HOME/.chrome-option" \
    --ignore-certificate-errors \
    --no-first-run \
    --no-default-browser-check \
    "$@"
