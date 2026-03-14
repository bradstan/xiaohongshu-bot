---
name: xhs-option
description: Publish professional option trading education content to Xiaohongshu account (期权). Includes NotebookLM-driven article writing, cover design, and automated publishing with review checkpoints.
---

# 小红书期权账号发布工作流

## 账号信息
- **账号名**: 期权（小红书-期权，主账号）
- **内容方向**: 美股期权教育（希腊字母、策略、波动率、卖方思维等）
- **发布频率**: 每天 2 篇（09:30 morning + 21:30 evening）
- **MCP Server**: `http://localhost:18060/mcp`
- **发布脚本**: `/Users/jarvis/xiaohongshu-mcp/publish.py`（使用 `/usr/bin/python3`）
- **Obsidian Vault**: `/Users/jarvis/Documents/小红书/`
  - 待发布文件夹: `待发布/`
  - 已发布文件夹: `已发布/`

## Overview
自动化期权教育内容制作与发布流程，从 NotebookLM 知识库回答改写到最终发布，全流程包含用户审核检查点。

## 内容生产 — NotebookLM 问答驱动（当前流程）

内容来源于用户的 NotebookLM 知识库（含知名期权和交易类经典书籍：Cottle、Sinclair、Cordier 等），保证文章专业性和权威性。

**流程（手动触发，待发布用完后重复）：**
1. **Claude 批量生成问题**：围绕 7 个期权/交易主题生成高质量问题
2. **用户喂给 NotebookLM**：用户将问题粘贴到 NotebookLM，获取基于书籍的专业回答
3. **Claude 改写为小红书文章**：将回答改写为小红书风格
   - 标题：≤20 字（简洁、吸引力）
   - 正文：≤950 字（XHS 限制 1000 但内部计数有偏差）
   - 话题标签：3-5 个
   - 输出到 `vault/待发布/`
4. **定时发布消耗文章**：`publish.py`（09:30/21:30）自动从待发布队列发布
5. **待发布用完后**：重复步骤 1-3

## 何时使用此 Skill

**使用场景：**
- 从 NotebookLM 回答改写期权教育文章
- 需要完整的发布流程：写文章 → 设计封面 → 用户审核 → 发布
- 批量生成期权主题问题供 NotebookLM 回答
- 快速迭代期权教育内容

**不使用此 Skill：**
- 仅需写文章（用通用写作工具）
- 仅需设计图片（用设计工具）
- 已有完整文章和图片，只需发布（直接跳到发布步骤）
- 宇宙能量账号内容（用 xiaohongshu-yuzhou-publisher）

## 核心工作流

### Phase 1: 文章创作

**1. 文章写作（从 NotebookLM 回答改写）**

从 NotebookLM 获得基于权威期权书籍的专业回答后，改写为小红书风格文章：

- **标题**：Hook 式标题（≤20 字）
  - 示例：「卖出看涨期权的本质是什么？」、「波动率微笑曲线详解」
- **正文**：≤950 字（保留空间防止内部计数偏差）
- **风格**：专业理性，面向有一定基础的散户投资者
- **结构**：清晰分段，便于阅读

**文章结构模板：**
```
标题：期权/交易主题（20字内）

开头：问题引入或场景描述
正文：
  🔥 现象/背景（为什么重要）
  💡 原理分析（深层机制）
  ⚡️ 实战应用（如何应用）
  💰 风险管理（注意事项）
  🎯 总结（核心要点）

结尾：互动提问，引导讨论
```

**2. 封面设计**

**当前使用方案：12 色 `options` 模板（期权主题配色）**

- ✅ 已在使用
- 💡 简洁、专业，适合期权教育内容
- 🎯 与期权账号风格一致

**设计流程：**

1. **使用 XHS 内置「文字配图」（推荐）**：
   - 快速、集成、无需外部工具
   - 80+ 模板风格（10 类 × 8 子类）
   - 自动填充内容
   - 专业质量

   **标题 vs 封面文案原则：**
   ```
   标题 (Title): 简洁吸引人 (≤20字)
     ↓  必须不同 ↓
   封面文案 (Cover Text): 展开说明、核心价值点、数据
   ```

   **示例：**
   - **标题**: 「卖出看涨期权的本质是什么？」
   - **封面文案**:
     ```
     Greeks 深度解析
     期权卖方必读
     掌握风险管理核心
     ```

2. **外部设计工具（备选）**：
   - 用 qiaomu-mondo-poster-design（Mondo 风格海报）
   - 用 Gemini Web / BigModel AI 等
   - 保持专业、简洁风格


### Phase 2: User Review

**3. Present Draft to User**
```markdown
## 📝 文章草稿

**标题：** [title]

**正文：** [content]

**图片：** [image paths or descriptions]

**话题标签：** [suggested hashtags]

---

请审核以上内容，确认后告诉我：
✅ "通过" - 我将立即发布
✅ "修改：[具体要求]" - 我将按你的要求调整
✅ "重新生成" - 我将重新创作
```

**4. Wait for User Approval**
- Do NOT proceed without explicit approval
- Acceptable approval signals:
  - "通过" / "ok" / "好的" / "发布"
  - Specific modification requests
- Revisions required? Update content → return to review step

### Phase 3: Publishing

**5. Publish to Xiaohongshu**

**Method Selection:**
- **Preferred:** Use mcp__xiaohongshu-mcp MCP tools
  - `publish_content` for image posts
  - `publish_with_video` for video posts
- **Fallback:** Use browser automation with playwright
  - Navigate to https://creator.xiaohongshu.com/publish/publish
  - Upload images
  - Fill title and content
  - Add hashtags
  - Click publish

**Publishing Checklist:**
- [ ] User approved content
- [ ] Images uploaded (local paths provided)
- [ ] Title formatted correctly (≤20 chars)
- [ ] Content formatted with line breaks
- [ ] Hashtags added (3-5 optimal)
- [ ] Publish button clicked
- [ ] Verify success message

## Quick Reference

| Step | Tool/Skill | Output |
|------|-----------|--------|
| 1. Write article | Content writing | Formatted markdown article |
| 2. Design images | baoyu-cover-image / baoyu-xhs-images | Image file paths |
| 3. Present draft | Markdown formatting | Review document |
| 4. Get approval | User communication | Approval confirmation |
| 5. Publish | mcp__xiaohongshu-mcp | Published post URL |

## Implementation

### 期权文章写作要点

**优质期权文章：**
- 开头从问题或实践场景引入
- 用 emoji 作为项目符号（🔥💡⚡️💰⚠️）
- 分段清晰，便于快速扫描
- 保持段落简洁（2-3 句）
- 结尾引导讨论和互动

**标题公式：**
- Pattern: [期权概念] + [实战价值] + [吸引力]
- 示例：
  - 「卖出看涨期权的本质是什么？」
  - 「Greeks 深度解析：期权卖方必读」
  - 「5 分钟掌握波动率微笑曲线」
  - 「期权卖方风险管理的核心」

### 话题标签策略

**选择 3-5 个相关话题：**
1. 广泛主题：#期权教育 #美股投资
2. 细分主题：#期权交易 #Greeks #波动率
3. 热门/趋势：检查 XHS 推荐话题

**研究热门话题：**
- 使用 xiaohongshu MCP 搜索工具
- 检查发布页面 "热门话题" 部分
- 平衡高热度和细分话题

### Image Design Guidelines

**For infographics:**
- Use baoyu-infographic skill
- Layout: 20+ types available
- Style: Professional, clean, readable

**For XHS carousel:**
- Use baoyu-xhs-images skill
- 9 visual styles available
- 6 layout options
- Optimize for mobile viewing

**For covers:**
- Use baoyu-cover-image skill
- Eye-catching main visual
- Clear title text
- Match brand colors

## 使用 MCP 工具发布

**期权账号 MCP Server：** `http://localhost:18060/mcp`

**示例：图文贴文**
```javascript
// 发布图文
mcp__xiaohongshu-mcp__publish_content({
  title: "卖出看涨期权的本质是什么？",
  content: "[完整正文内容]",
  images: ["/path/to/cover.png"],
  tags: ["期权教育", "Greeks", "卖方思维"],
  schedule_at: "2026-03-13T09:30:00+08:00" // 可选：定时发布
})
```

**示例：视频贴文**
```javascript
// 发布视频
mcp__xiaohongshu-mcp__publish_with_video({
  title: "期权波动率微笑曲线详解",
  content: "[完整正文内容]",
  video: "/path/to/video.mp4",
  tags: ["期权教育", "波动率", "技术分析"]
})
```

**错误处理：**
- 证书错误 → 使用浏览器自动化备用方案
- 需要登录 → **使用浏览器登录流程（见下文）**
- 上传失败 → 验证文件路径和格式
- 超时（>150s）→ 检查 MCP server 状态
- 频率限制 → 等待后重试

## Login Flow (Browser-Based)

XHS no longer supports single QR code scan. Always use the browser login binary:

### When `check_login_status` returns ❌ 未登录:

**Step 1: Run the browser login binary**
```bash
cd ~/xiaohongshu-mcp && ./xiaohongshu-login-darwin-arm64 -bin "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```
Run this via the Bash tool. It will open a Chrome browser window.

**Step 2: Tell user to log in**
Tell the user: "浏览器已打开，请在 Chrome 窗口中完成小红书登录（可能需要扫码两次），完成后告诉我。"

**Step 3: Wait for user confirmation**
Do NOT proceed until the user confirms they have successfully logged in.

**Step 4: Restart MCP server**
```bash
cd ~/xiaohongshu-mcp && bash start_mcp.sh
```

**Step 5: Verify login**
Call `check_login_status` again to confirm ✅ 已登录.

### ❌ NEVER use `get_login_qrcode`
The QR code login tool is broken — XHS now requires scanning twice which the tool cannot handle.


## 常见错误

### ❌ 跳过用户审核
**不好：** 生成内容 → 立即发布
**正确：** 生成内容 → 呈现审核 → 等待批准 → 发布

### ❌ 标题长度不对
**不好：** 50+ 字的超长标题会被截断
**正确：** ≤20 字，优化 XHS 显示

### ❌ 正文超过上限
**不好：** 1000+ 字的冗长文章
**正确：** ≤950 字，保留余量防止内部计数偏差

### ❌ 图片质量差
**不好：** GIF、Live Photo 或低分辨率
**正确：** PNG/JPG/WEBP，≥720×960，3:4 到 2:1 比例

### ❌ 没有话题标签
**不好：** 没有标签，可发现性低
**正确：** 3-5 个相关标签，平衡广泛和细分话题

### ❌ 忽视期权风格
**不好：** 学术、教科书式语言
**正确：** 专业理性、实战导向、面向散户投资者

## 现实影响

**之前：**
- 手工写文章：30-60 分钟
- 图片设计工具学习：1-2 小时
- 手工发布过程：5-10 分钟
- 总时间：1.5-3 小时

**之后：**
- 自动改写文章：1-2 分钟（从 NotebookLM 回答）
- 自动设计图片：2-3 分钟
- 自动发布：1-2 分钟
- 用户审核时间：2-5 分钟
- 总时间：6-12 分钟

**效率提升：** 10-15 倍，一致的质量，内置审核检查点

## 示例会话

**用户：** "帮我从 NotebookLM 的期权回答改写一篇文章，然后发布"

**助手：**
1. Claude 改写 NotebookLM 回答为小红书风格（标题≤20字、正文≤950字）
2. 使用 qiaomu-mondo-poster-design 生成专业封面图片
3. 呈现草稿审核：
   ```markdown
   ## 📝 文章草稿

   **标题：** 卖出看涨期权的本质是什么？

   **正文：** [完整正文内容...]

   **图片：** [cover.png]

   **话题标签：** #期权教育 #Greeks #卖方思维

   ---

   请审核：✅通过 / ✅修改 / ✅重新生成
   ```
4. 用户：「✅通过」
5. 使用 mcp__xiaohongshu-mcp (port:18060) 发布
6. 确认：「发布成功！笔记链接：[URL]」

## 高级功能

### 定时发布
```javascript
// 计划在特定时间发布
schedule_at: "2026-03-13T09:30:00+08:00" // ISO 8601 格式
// 支持：提前 1 小时到 14 天
```

### 多图贴文
- XHS 支持每篇最多 18 张图片
- 第一张图片 = 封面图
- 在浏览器 UI 中拖动重新排序
- 保持图片风格一致

### 内容合集
- 使用 "添加合集" 功能
- 将相关贴文分组
- 提高可发现性

### 话题积累
- 持续发布期权教育内容
- 建立账号权威性
- 吸引目标受众关注
