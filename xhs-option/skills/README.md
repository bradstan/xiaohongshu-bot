# 小红书发布 Skills

本目录包含两个 Claude Code Skills，用于自动化小红书期权账号和宇宙能量账号的内容发布流程。

## 📚 Skills 说明

### 1. `xhs-option` - 期权账号发布

**用途**：自动化期权教育内容的写作、设计和发布

**账号信息**：
- 账号名：期权（小红书-期权，主账号）
- MCP Server：`http://localhost:18060/mcp`
- 发布频率：每天 2 篇（09:30 morning + 21:30 evening）
- 内容方向：美股期权教育（Greeks、波动率、卖方思维等）

**工作流**：
1. Claude 从 NotebookLM 回答改写期权教育文章
2. 生成专业封面图（options 12色模板）
3. 用户审核
4. 自动发布到小红书

**规范**：
- 标题：≤20 字
- 正文：≤950 字
- 话题标签：3-5 个

---

### 2. `xhs-energy` - 宇宙能量账号发布

**用途**：自动化精神能量和显化内容的写作、设计和发布

**账号信息**：
- 账号名：宇宙能量（yuzhou）
- MCP Server：`http://localhost:18061/mcp`
- 发布频率：每天 3 篇（10:18 + 14:18 + 22:18）
- 内容方向：宇宙能量、吸引力法则、显化、福气人设

**工作流**：
1. Claude 从 NotebookLM 回答改写宇宙能量文章（fiya 风格）
2. 生成温暖柔和的封面图（纯底图，不叠文字）
3. 用户审核
4. 自动发布到小红书

**规范**：
- 标题：≤20 字
- 正文：300-450 字（日记感）
- 风格：温柔女性心灵导师，`·` 分节，无粗体
- 话题标签：3-5 个

---

## 🚀 安装与使用

### 安装 Skills

将这两个 skills 复制到 Claude Code 的 skills 目录：

```bash
cp -r xhs-option ~/.claude/skills/
cp -r xhs-energy ~/.claude/skills/
```

### 在 Claude 中使用

在对话中直接调用：
- `/xhs-option` - 期权账号发布工作流
- `/xhs-energy` - 宇宙能量账号发布工作流

或者在创建新贴文时自动显示在 skills 菜单中。

---

## 📋 内容生产流程

### 期权账号（xhs-option）

**准备阶段**：
1. 用户准备 NotebookLM 知识库（含期权和交易类经典书籍）
2. Claude 批量生成 7 个期权/交易主题问题

**生产循环**：
1. 用户喂给 NotebookLM，获取基于书籍的专业回答
2. Claude 改写为小红书文章（标题≤20字、正文≤950字）
3. 生成封面图
4. 用户审核
5. 定时发布（09:30/21:30）
6. 文章消耗完后重复步骤 1-5

---

### 宇宙能量账号（xhs-energy）

**准备阶段**：
1. 用户准备 NotebookLM 知识库（含灵性经典书籍）
2. Claude 批量生成 7 个福气/显化/爱情等主题问题

**生产循环**：
1. 用户喂给 NotebookLM，获取基于书籍的专业回答
2. Claude 改写为小红书文章（fiya 风格、300-450字）
3. 生成温暖柔和的封面图
4. 用户审核
5. 定时发布（10:18/14:18/22:18）
6. 文章消耗完后重复步骤 1-5

---

## 🔑 关键配置

### MCP Servers

**期权账号**：
```
Server: xiaohongshu-mcp-darwin-arm64
URL: http://localhost:18060/mcp
Python: /usr/bin/python3
```

**宇宙能量账号**：
```
Server: 单独实例
URL: http://localhost:18061/mcp
Python: venv python（非 /usr/bin/python3）
```

### 文件夹结构

**期权账号**：
```
/Users/jarvis/Documents/小红书/
├── 待发布/
└── 已发布/
```

**宇宙能量账号**：
```
/Users/jarvis/Documents/宇宙能量/
├── 待发布/
└── 已发布/
```

---

## 🛠 发布脚本

**期权账号**：
```bash
/Users/jarvis/xiaohongshu-mcp/publish.py
```

**宇宙能量账号**：
```bash
/Users/jarvis/xiaohongshu-yuzhou/publish.py
```

定时发布由 launchd 配置，具体见项目 launchd/ 目录。

---

## 📝 API 工具参考

### 发布图文

```javascript
mcp__xiaohongshu-mcp__publish_content({
  title: "标题（≤20字）",
  content: "[完整正文内容]",
  images: ["/path/to/cover.png"],
  tags: ["标签1", "标签2", "标签3"],
  schedule_at: "2026-03-13T09:30:00+08:00" // 可选
})
```

### 发布视频

```javascript
mcp__xiaohongshu-mcp__publish_with_video({
  title: "标题（≤20字）",
  content: "[完整正文内容]",
  video: "/path/to/video.mp4",
  tags: ["标签1", "标签2"]
})
```

### 检查登录状态

```javascript
mcp__xiaohongshu-mcp__check_login_status()
```

### 浏览器登录

```bash
cd ~/xiaohongshu-mcp && ./xiaohongshu-login-darwin-arm64 -bin "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

---

## 📚 更多文档

详细的工作流和最佳实践见各 skill 的 SKILL.md 文件：
- `xhs-option/SKILL.md` - 期权账号完整指南
- `xhs-energy/SKILL.md` - 宇宙能量账号完整指南

---

## 🔄 版本信息

- 创建日期：2026-03-13
- 期权账号待发布存货：13 篇
- 宇宙能量账号待发布存货：17 篇
- 技术文档：`/Users/jarvis/Documents/小红书/小红书Bot Pipeline 技术文档.md` (v2.3)

---

**维护者**：Jarvis
**项目地址**：https://github.com/bradstan/xiaohongshu-bot
