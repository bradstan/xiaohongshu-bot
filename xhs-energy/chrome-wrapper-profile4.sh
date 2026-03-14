#!/bin/bash
# Chrome wrapper for 宇宙能量账号（SS心灵疗愈所）
# 固定使用 Chrome Profile 4（badstan）
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --profile-directory="Profile 4" \
    --ignore-certificate-errors \
    "$@"
