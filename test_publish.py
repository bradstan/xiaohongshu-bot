#!/usr/bin/env python3
"""
使用模拟 MCP 服务器测试完整发布流程。
运行此脚本可以在没有真实小红书账号的情况下验证发布逻辑。
"""
import sys
import time
import threading
from pathlib import Path

# 启动模拟服务器
sys.path.insert(0, str(Path(__file__).parent))
from mock_mcp_server import start as start_mock_server

print("启动模拟 MCP 服务器...")
server = start_mock_server(port=18060)
time.sleep(0.5)  # 等待服务器就绪

# 运行发布脚本（直接调用 main 函数，不用 subprocess）
from publish import main
main()

server.shutdown()
print("\n模拟发布流程完成！")
