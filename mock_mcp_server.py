#!/usr/bin/env python3
"""
模拟 xiaohongshu-mcp HTTP 服务器，用于本地测试发布流程。
响应 publish_content、search_feeds 等工具调用，返回模拟数据。
"""
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

SESSION_ID = "mock-session-001"
MOCK_FEED_ID = "mock-feed-" + datetime.now().strftime("%Y%m%d%H%M%S")
MOCK_XSEC_TOKEN = "mock-xsec-token-abc123"

class MCPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[mock-mcp] {format % args}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body)
        except Exception:
            self.send_error(400, "Bad JSON")
            return

        method = req.get("method", "")
        req_id = req.get("id", 1)

        if method == "initialize":
            resp_body = json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "mock-xhs", "version": "1.0"}}
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", SESSION_ID)
            self.send_header("Content-Length", str(len(resp_body.encode())))
            self.end_headers()
            self.wfile.write(resp_body.encode())
            return

        if method == "tools/call":
            tool = req.get("params", {}).get("name", "")
            args = req.get("params", {}).get("arguments", {})

            if tool == "publish_content":
                title = args.get("title", "")
                content = args.get("content", "")
                tags = args.get("tags", [])
                images = args.get("images", [])
                print(f"\n{'='*50}")
                print(f"[mock-mcp] ✅ 模拟发布成功！")
                print(f"[mock-mcp]   标题: {title}")
                print(f"[mock-mcp]   正文长度: {len(content)} 字符")
                print(f"[mock-mcp]   标签: {tags}")
                print(f"[mock-mcp]   图片: {len(images)} 张")
                print(f"[mock-mcp]   模拟 feed_id: {MOCK_FEED_ID}")
                print(f"{'='*50}\n")
                result_text = json.dumps({
                    "success": True,
                    "message": "发布成功",
                    "feed_id": MOCK_FEED_ID,
                })
            elif tool == "search_feeds":
                keyword = args.get("keyword", "")
                print(f"[mock-mcp] 搜索关键词: {keyword}")
                # 返回与关键词完全匹配的条目，模拟发布后能找到 feed_id
                result_text = json.dumps({
                    "feeds": [
                        {
                            "id": MOCK_FEED_ID,
                            "xsecToken": MOCK_XSEC_TOKEN,
                            "noteCard": {
                                "displayTitle": keyword,
                                "user": {"userId": "54808b57d6e4a9616b300900"},
                            }
                        }
                    ]
                })
            else:
                result_text = json.dumps({"message": f"tool {tool} not mocked"})

            resp_body = json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": result_text}]}
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", SESSION_ID)
            self.send_header("Content-Length", str(len(resp_body.encode())))
            self.end_headers()
            self.wfile.write(resp_body.encode())
            return

        self.send_error(404, f"Unknown method: {method}")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"mock-mcp-server OK")


def start(port=18060):
    server = HTTPServer(("127.0.0.1", port), MCPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[mock-mcp] 模拟 MCP 服务器已启动，端口 {port}")
    return server


if __name__ == "__main__":
    import time
    server = start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
