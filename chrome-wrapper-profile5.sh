#!/bin/bash
# Chrome wrapper for 期权账号（wick123）
# 固定使用 Chrome Profile 5
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --profile-directory="Profile 5" \
    --ignore-certificate-errors \
    "$@"
