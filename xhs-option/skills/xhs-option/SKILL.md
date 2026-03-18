---
name: xhs-option
description: Publish professional option trading education content to Xiaohongshu account (期权). Includes NotebookLM-driven article writing, cover design, and automated publishing with review checkpoints.
---

# 期权账号发布 Skill

## ⚠️ 账号绑定（每次必须先执行）
- 专属账号：**wick123（期权）**，MCP 工具前缀：`mcp__xhs-option__`
- **第一步**：调用 `mcp__xhs-option__check_login_status`
  - 返回含 "wick123" → 继续
  - 返回未登录 → 执行下方登录流程，**不得跳过**

---

## 执行步骤

**Step 1 — 写文章**（从 NotebookLM 回答改写）
- 标题 ≤20字，正文 ≤950字，话题标签 3-5个
- 风格：像懂期权的朋友在聊天，不是教科书
- 结构：场景/痛点引入 → 核心原理 → 实战应用 → 互动收尾
- 允许 1-2 段 bullet list，禁止 3 个以上 `##` 二级标题

**禁用词**（一出现即是 AI 腔）：
> 简单来说 / 值得注意的是 / 总的来说 / 首先…其次…最后 / 不得不说 / 相信很多人

**Step 2 — 生成封面**
```bash
cd /Users/jarvis/xiaohongshu-bot/xhs-option && python3 make_cover.py
```
或调用 `qiaomu-mondo-poster-design`（专业简洁风）

**Step 3 — 呈现草稿，等待用户审核**
```
## 📝 文章草稿
标题：[title]
正文：[content]
图片：[cover path]
标签：[tags]
---
✅ 通过 / ✅ 修改：[要求] / ✅ 重新生成
```
**不得在未获明确审核前发布。**

**Step 4 — 发布**
```javascript
mcp__xhs-option__publish_content({
  title: "标题（≤20字）",
  content: "正文（≤950字）",
  images: ["/path/to/cover.png"],
  tags: ["期权教育", "美股期权", "..."]
})
```

**Step 5 — 归档**
将文章写入 `/Users/jarvis/xiaohongshu-bot/xhs-option/vault/待发布/YYYY-MM-DD｜标题.md`，frontmatter 含 `date / tags / category: options / theme_id`

---

## 登录流程（仅在 check_login_status 返回 ❌ 未登录时）

```bash
cd /Users/jarvis/xiaohongshu-bot/xhs-option && ./xiaohongshu-login-darwin-arm64 -bin "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```
→ 告知用户："浏览器已打开，请扫码登录（需扫码两次），完成后告诉我"
→ 等用户确认 → `bash start_mcp.sh` → 再次 `check_login_status` 验证

❌ **禁止使用 `get_login_qrcode`**（已失效，XHS 需扫码两次）

---

## 常见错误速查
| 错误 | 处置 |
|------|------|
| 超时 >150s | 检查 MCP server：`nc -z 127.0.0.1 18060` |
| 发布失败 isError=true | 检查登录状态，重新登录 |
| 正文超限 | 删减至 ≤950字，留意内部计数偏差 |
| 标题截断 | 确保 ≤20字 |

> 详细参考（写作风格、标签策略、高级功能）→ `SKILL-GUIDE.md`
