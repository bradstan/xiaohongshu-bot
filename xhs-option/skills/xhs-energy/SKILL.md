---
name: xhs-energy
description: Publish spiritual and manifestation content to Xiaohongshu account (宇宙能量). Warm, nurturing feminine energy guide style with NotebookLM-driven content, cover design, and automated publishing.
---

# 宇宙能量账号发布 Skill

## ⚠️ 账号绑定（每次必须先执行）
- 专属账号：**SS心灵疗愈所（宇宙能量）**，MCP 工具前缀：`mcp__xhs-energy__`
- **第一步**：调用 `mcp__xhs-energy__check_login_status`
  - 返回含 "SS心灵疗愈所" → 继续
  - 返回未登录 → 执行下方登录流程，**不得跳过**

---

## 执行步骤

**Step 1 — 写文章**（从 NotebookLM 回答改写，仿 fiya 风格）
- 标题 ≤20字，正文 300-450字，话题标签 3-5个
- 风格：温柔女性心灵导师，日记感，第一人称或亲切感
- 结构：日记式开场 → `·` 分节（3-4节）→ 福气钩子收尾
- **禁止**：粗体、emoji 列表、命令式语气、超过 450字

**必备风格规则**：
- 用 `·` 分节，不用数字或 emoji 列表
- 结尾必须有互动钩子（"刷到这篇的人…" / "留言的人…"）
- 开场示例："今天想和你分享…" / "刚刚有个想法…"

**Step 2 — 生成封面**（纯底图，不叠文字）
- 调用 `qiaomu-mondo-poster-design`：温暖配色，粉/紫/金/米色系，简洁留白
- 或使用 XHS 内置「文字配图」选柔和简约模板

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
mcp__xhs-energy__publish_content({
  title: "标题（≤20字，温暖有吸引力）",
  content: "正文（300-450字，· 分节）",
  images: ["/path/to/cover.png"],
  tags: ["宇宙能量", "显化", "吸引力法则", "..."]
})
```

**Step 5 — 归档**
将文章写入 `/Users/jarvis/Documents/宇宙能量/待发布/YYYY-MM-DD｜标题.md`，frontmatter 含 `date / tags / category: yuzhou / theme_id`

---

## 登录流程（仅在 check_login_status 返回 ❌ 未登录时）

```bash
cd /Users/jarvis/xiaohongshu-bot/xhs-energy && ./xiaohongshu-login-darwin-arm64 -bin "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```
→ 告知用户："浏览器已打开，请扫码登录（需扫码两次），完成后告诉我"
→ 等用户确认 → `bash start_mcp.sh` → 再次 `check_login_status` 验证

❌ **禁止使用 `get_login_qrcode`**（已失效，XHS 需扫码两次）

---

## 常见错误速查
| 错误 | 处置 |
|------|------|
| 超时 >150s | 检查 MCP server：`nc -z 127.0.0.1 18061` |
| 发布失败 isError=true | 检查登录状态，重新登录 |
| 正文超限 | 删减至 ≤450字 |
| 风格跑偏（硬、说教） | 重写开场为日记感，去粗体，加 `·` 分节 |

> 详细参考（选题方向、标签策略、fiya 风格范例）→ `SKILL-GUIDE.md`
