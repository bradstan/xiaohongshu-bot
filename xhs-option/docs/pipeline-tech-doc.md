---
tags: [技术文档]
date: 2026-03-07
version: v2.3
---

# 小红书Bot Pipeline 技术文档 v2.3

小红书内容管线：NotebookLM 知识库驱动的期权教育内容生产 + 定时发布 + 数据采集 + AI复盘。

> **v2.3 变更**：Track B（AI工具热帖）已暂停；Track A 改为 NotebookLM 问答驱动的批量文章生产流程。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│              内容生产 — NotebookLM 问答驱动                      │
│                                                                  │
│  ① Claude 批量生成问题（围绕期权/交易主题）                      │
│  ② 用户将问题喂给 NotebookLM（经典书籍知识库）                  │
│  ③ NotebookLM 批量回答                                          │
│  ④ Claude 将回答改写为小红书文章 ──→ vault/待发布/              │
│  ⑤ 待发布用完后，重复 ①-④                                      │
└─────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────┐
│                          发布 & 反馈                             │
│                                                                  │
│  publish.py ──→ 小红书MCP ──→ vault/已发布/  ←── feedback.py   │
│  (09:30/21:30)               互动数据+AI复盘    (每30分钟)      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              Track B — AI工具热帖（⏸️ 已暂停）                    │
│  scanner.py / translator.py — launchd 任务已停用                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
~/xiaohongshu-mcp/
│
├── pipeline/                     # v2.0 模块化管线
│   ├── track_a/
│   │   ├── curator.py            # 每周精选英文期权教育素材
│   │   ├── writer.py             # 文章写作（注入书籍知识 + 精选素材）
│   │   └── knowledge.py          # 知识库加载器
│   └── track_b/
│       ├── scanner.py            # 每日 Twitter/Reddit 热帖扫描
│       └── translator.py         # 热帖翻译 + 本土化为小红书文章
│
├── knowledge_base/               # NotebookLM 期权书籍精华（7个主题）
│   ├── options_basics.md
│   ├── greeks_explained.md
│   ├── strategy_playbook.md
│   ├── leaps_guide.md
│   ├── risk_and_mindset.md
│   ├── options_vs_stocks.md
│   └── earnings_and_events.md
│
├── state/                        # 运行时状态
│   ├── curated/                  # Track A 精选素材（YYYY-WNN-options.json/.md）
│   ├── scans/                    # Track B 每日扫描结果（YYYY-MM-DD.json）
│   └── theme_weights.json        # 主题权重（feedback驱动动态调整）
│
├── vault/                        # Obsidian Vault 根目录
│   ├── 待审核/                   # Track A 输出，人工审核后移至 待发布/
│   ├── 待发布/                   # 发布队列（publish.py 消费）
│   └── 已发布/                   # 发布完成（含互动数据 + AI复盘）
│
├── launchd/                      # macOS LaunchAgent plist 配置
│   ├── com.jarvis.xhs-mcp-server.plist
│   ├── com.jarvis.xhs-curate-weekly.plist
│   ├── com.jarvis.xhs-scan-daily.plist
│   ├── com.jarvis.xhs-translate-daily.plist
│   ├── com.jarvis.xhs-publish-morning.plist
│   └── com.jarvis.xhs-publish-evening.plist
│
├── logs/                         # 集中日志目录
│   ├── mcp-server.log / .err
│   ├── curate-weekly.log / .err
│   ├── scan-daily.log / .err
│   ├── translate-daily.log / .err
│   ├── publish-morning.log / .err
│   └── publish-evening.log / .err
│
├── covers/                       # 生成的封面图（cover_<hash>.jpg）
├── templates/                    # 提示词模板（prompts/）
│
├── publish.py                    # 定时发布主脚本
├── feedback.py                   # 互动数据采集 + AI复盘
├── make_cover.py                 # PIL 封面图生成（双模板）
├── mark_published.py             # 文件重命名（加 ✅ 前缀）
├── llm.py                        # Claude CLI 统一调用模块
├── notebooklm_sync.py            # NotebookLM 知识库同步工具（交互式）
├── research.py                   # 旧版（保留兼容）
│
├── start_mcp.sh                  # MCP server 启动/保活（nc 端口检测 + /usr/sbin/lsof 清理）
├── run_publish.sh                # 发布 wrapper（launchd 入口，PATH 含 /usr/sbin）
├── run_research.sh               # 研究 wrapper（launchd 入口）
├── run_feedback.sh               # 反馈 wrapper（launchd 入口）
├── browser-login.sh              # 一键浏览器登录（备份cookie → 启动登录 → 重启MCP）
├── chrome-wrapper.sh             # Chrome 启动包装（--ignore-certificate-errors）
├── sync_cookies_from_chrome.py   # Chrome cookie 同步（pycookiecheat 解密，智能跳过）
│
├── venv/                         # Python virtualenv（pycookiecheat 等依赖）
│
├── topics.json                   # 账号定位 & 7个主题配置
├── published.json                # 全局发布状态追踪
├── cookies.json                  # 小红书登录态
├── cookies.json.bak              # 登录前自动备份
│
├── xiaohongshu-mcp-darwin-arm64  # MCP server 二进制
└── xiaohongshu-login-darwin-arm64 # 浏览器登录工具（Chrome + 扫码两次）
```

Obsidian 通过 symlink 访问 vault：
- `~/Documents/小红书/待审核` → `~/xiaohongshu-mcp/vault/待审核`
- `~/Documents/小红书/待发布` → `~/xiaohongshu-mcp/vault/待发布`
- `~/Documents/小红书/已发布` → `~/xiaohongshu-mcp/vault/已发布`

---

## 核心流程详解

### 内容生产 — NotebookLM 问答驱动

**核心理念**：文章内容来源于 NotebookLM 中的经典期权/交易书籍知识库（Cottle、Sinclair、Cordier 等），保证专业性和权威性。Claude 负责提问和改写，NotebookLM 负责基于书籍知识回答。

#### 步骤1：Claude 批量生成问题

**触发**：手动（在 Claude Code 中执行）

Claude 围绕期权/交易 7 个主题生成一批高质量问题，覆盖入门概念、Greeks、策略、LEAPS、风控等方向。问题设计面向小红书受众（投资新手 → 进阶者）。

#### 步骤2：NotebookLM 批量回答

**触发**：手动（用户将问题粘贴到 NotebookLM）

用户将问题喂给 NotebookLM，它基于导入的经典期权书籍生成专业回答。这一步确保内容源于权威书籍，而非 AI 凭空生成。

#### 步骤3：Claude 改写为小红书文章

**触发**：手动（在 Claude Code 中执行）

Claude 将 NotebookLM 的回答改写为小红书风格文章：
1. 标题（20 字以内）、正文（≤950 字）、话题标签
2. 添加 frontmatter（date、category、theme_id 等）
3. QA 检查（字数、格式）
4. 输出到 `vault/待发布/`

#### 步骤4：循环

当 `vault/待发布/` 中的文章被定时发布消耗完毕后，重复步骤 1-3 补充新文章。

**文章格式**：
```markdown
---
tags: [小红书, 投资]
date: 2026-03-01
version: v1.0
word_count: 900
theme_id: strategy_playbook
category: options
---

# 标题（20字以内）

正文...

---

#期权 #美股期权 #标签3 ...

⚠️ 仅为知识分享，不构成投资建议。
```

### Track B — AI工具热帖快译（⏸️ 已暂停）

Track B（scanner.py + translator.py）的 launchd 定时任务已停用。相关代码保留但不再运行。如需恢复，重新加载对应 launchd plist 即可。

---

### 发布（publish.py）

**触发**：launchd 每天 09:30 和 21:30

**关键参数**：
- 正文字数上限：**950 字**（小红书实际限制 1000，但其内部计数与 Python `len()` 有偏差，留 50 余量）
- MCP 调用默认超时：90s
- `publish_content` 超时：**150s**（发布含图片上传，耗时较长）
- 超长正文自动截断并加 `...`

**流程**：

1. `start_mcp.sh` 确保 MCP server 运行
2. 扫描 `vault/待发布/` 中的 `.md` 文件
3. 对比 `published.json` 排除已发布的文件
4. 解析文章：frontmatter、H1标题、正文、tags
5. `generate_cover()`：按 `category` 字段选封面模板
6. MCP `publish_content`（timeout=150s）：发布图文到小红书
7. 搜索获取 `feed_id` 并更新 `published.json`
8. 文件重命名（加 ✅ 前缀）+ 移动到 `已发布/`

---

### 互动数据采集 + AI复盘（feedback.py）

**触发**：launchd 每 30 分钟执行

**Checkpoint 机制**：

| 时间点 | 目的 |
|--------|------|
| 30分钟 | 初始流量 |
| 1小时  | 冷启动表现 |
| 3小时  | 推荐池表现 |
| 6小时  | 稳定期数据 |
| 24小时 | 最终表现 |

**流程**：
1. 遍历 `published.json` 所有文章
2. `feed_id` 为空且发布 < 48h 时，重试搜索（短标题 + 主页匹配）
3. 对到达时间点的文章调用 `get_feed_detail` 拉取点赞/收藏/评论/分享
4. 将数据追加写入文章末尾的追踪表格
5. 有 6h 以上数据时，调用 Claude 生成 AI 复盘摘要，插入文章顶部
6. AI 复盘完成后，文件名 emoji 从 ✅ 改为 📊
7. 用复盘数据更新 `state/theme_weights.json`（高表现主题权重上升）

**复盘区块示例**：
```markdown
<!-- 复盘数据 -->
> 📊 **互动数据** | 更新于 2026-03-01 10:00

| 时间点 | 点赞 | 收藏 | 评论 | 分享 |
|--------|------|------|------|------|
| 30分钟 | 5 | 15 | 0 | 0 |
| 6小时  | 8 | 22 | 2 | 1 |

> **AI 复盘**：收藏率优秀但评论为零，建议结尾增加互动提问。
<!-- /复盘数据 -->
```

---

## 封面图生成（make_cover.py）

v2.0 新增双模板，按文章 `category` 字段自动选择：

| 模板 | 适用 | 风格 | 配色数 | 状态 |
|------|------|------|--------|------|
| `options` | 期权教育文章 | 深色渐变背景，金融质感，浅色大字标题 | 12 色 | ✅ 使用中 |
| `ai_tools` | AI工具文章 | 白/浅色底，纯色色带标题，深色正文，左边框要点块 | 12 色 | ⏸️ Track B 暂停 |

- 每次发布随机选色，12 种配色保证视觉不重复
- 封面自动提取正文 `**粗体**` 或 `## 标题` 作为 bullet points（最多 3 条）
- 尺寸：1080×1440（3:4 竖版，小红书标准）
- 字体：系统 STHeiti
- 输出：`covers/cover_<hash>.jpg`

---

## 知识库（NotebookLM — 核心内容源）

NotebookLM 是整个内容管线的**核心知识源**。用户的 NotebookLM 笔记本收录了知名期权和交易类书籍（Cottle、Sinclair、Cordier 等），所有文章内容最终来源于此，保证专业性。

**角色**：
- **v2.2 及之前**：`knowledge_base/` 目录存储 7 个主题精华文件，作为 writer.py prompt 的素材注入
- **v2.3 起**：NotebookLM 直接参与内容生产——Claude 提问 → NotebookLM 回答 → Claude 改写文章

**7个主题覆盖**：

| 主题 | 说明 |
|------|------|
| 期权入门概念 | 基础术语、合约要素、买卖方 |
| Greeks 实战解读 | Delta/Gamma/Theta/Vega/Rho |
| 期权策略图鉴 | Spread、Straddle、Iron Condor 等 |
| LEAPS 长期期权 | 长期持有策略、优势与风险 |
| 风控与交易心态 | 仓位管理、止损、心理纪律 |
| 期权 vs 股票 | 杠杆对比、收益结构差异 |
| 财报季期权科普 | IV Crush、事件驱动策略 |

**本地知识库文件**（`knowledge_base/`，历史遗留，现主要由 NotebookLM 直接提供内容）：
```bash
cd ~/xiaohongshu-mcp
python3 notebooklm_sync.py          # 交互式全量更新
python3 notebooklm_sync.py --list   # 查看填充状态
python3 notebooklm_sync.py --theme strategy_playbook  # 更新单个主题
```

---

## 调度系统（macOS launchd）

| 任务 | plist | 调度 | 状态 |
|------|-------|------|------|
| MCP server 保活 | `com.jarvis.xhs-mcp-server` | 开机启动 + 崩溃自重启 | ✅ 运行中 |
| 早间发布 | `com.jarvis.xhs-publish-morning` | 每天 09:30 | ✅ 运行中 |
| 晚间发布 | `com.jarvis.xhs-publish-evening` | 每天 21:30 | ✅ 运行中 |
| Cookie 同步 | `com.jarvis.xhs-sync-cookies` | 每天 03:00 | ✅ 运行中 |
| ~~Track B 扫描~~ | `com.jarvis.xhs-scan-daily` | ~~每天 07:00~~ | ⏸️ 已暂停 |
| ~~Track B 翻译~~ | `com.jarvis.xhs-translate-daily` | ~~每天 07:30~~ | ⏸️ 已暂停 |
| ~~Track A 精选~~ | `com.jarvis.xhs-curate-weekly` | ~~每周日 07:00~~ | ⏸️ 已弃用（改为 NotebookLM 流程） |

**launchd PATH 注意**：launchd 环境 PATH 极度受限（无 `/usr/sbin`），已在各 wrapper 脚本中手动补充：
- `run_publish.sh`：`export PATH="/usr/sbin:/opt/homebrew/bin:/usr/local/bin:$PATH"`
- `start_mcp.sh`：端口检测用 `nc`（不依赖 lsof），清理用完整路径 `/usr/sbin/lsof`

---

## MCP Server

小红书 API 交互通过 MCP（Model Context Protocol）server：

- 二进制：`xiaohongshu-mcp-darwin-arm64`
- 协议：JSON-RPC 2.0 over HTTP
- 端口：18060
- 登录态：`cookies.json`
- 运行模式：headless

**主要 API**：

| 工具名 | 用途 |
|--------|------|
| `publish_content` | 发布图文笔记 |
| `search_feeds` | 搜索笔记（查 feed_id）|
| `get_feed_detail` | 获取互动数据 |
| `check_login_status` | 检查登录状态 |

**登录方式（浏览器登录）**：

小红书已于 2026 年初更改登录流程，需要扫码两次确认，MCP 的 `get_login_qrcode` 工具已无法使用。

> ⚠️ **NEVER use `get_login_qrcode`** — 已失效。

唯一登录方式：
```bash
cd ~/xiaohongshu-mcp && bash browser-login.sh
```
流程：打开真实 Chrome 窗口 → 小红书扫码登录（需扫两次）→ cookies 自动保存 → MCP server 自动重启

也可手动执行底层命令：
```bash
cd ~/xiaohongshu-mcp
./xiaohongshu-login-darwin-arm64 -bin "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
bash start_mcp.sh
```

**Cookie 持久化（自动同步）**：

登录后的 session（`web_session`）会在一段时间不活跃后由小红书服务端过期。延长登录状态的方式：

1. **Chrome 浏览续命**：在 Chrome（Profile 4）中偶尔访问小红书，Chrome 会自动刷新 token
2. **每日自动同步**：`com.jarvis.xhs-sync-cookies`（每天 03:00）运行 `sync_cookies_from_chrome.py`，将 Chrome 中更新的 cookies 同步到 `cookies.json`

`sync_cookies_from_chrome.py` 智能跳过逻辑：
- 若 `cookies.json` 不足 12 小时（刚手动登录），跳过同步
- 若 Chrome cookies 比 `cookies.json` 更旧，跳过同步
- 仅在 Chrome 确实有更新鲜的 cookies 时才同步并重启 MCP server

依赖：`pycookiecheat`（安装在 `venv/` 中），支持 Chrome AES-128-CBC 和 AES-256-GCM 两种加密格式

---

## LLM 调用（llm.py）

统一 Claude CLI 调用模块。

- 命令：`claude --print --max-turns 1 -p "prompt"`
- 认证：OAuth token（`~/.config/anthropic/oauth_token`）
- 超时：180s

**⚠️ 重要**：在 Claude Code 会话内运行 Python 脚本调 LLM 时，需绕过嵌套会话限制：

```bash
env -u CLAUDECODE python3 pipeline/track_a/writer.py
```

---

## 状态文件

### published.json

```json
{
  "published": [
    {
      "file": "vault/已发布/✅2026-03-01｜标题.md",
      "title": "文章标题",
      "published_at": "2026-03-01T09:30:15",
      "feed_id": "abc123...",
      "xsec_token": "ABxxx...",
      "theme_id": "strategy_playbook",
      "category": "options",
      "checkpoints": {
        "30分钟": { "liked": 5, "collected": 15, "comment": 0, "shared": 0 },
        "24小时": { "liked": 12, "collected": 30, "comment": 3, "shared": 1 }
      }
    }
  ]
}
```

### state/theme_weights.json

反馈驱动的主题权重，高收藏/点赞率的主题权重上升，writer.py 按权重轮转选题。

---

## 已知限制 & 注意事项

1. **登录过期**：小红书 session 在不活跃后会被服务端过期（具体时长不确定，约数天至 1-2 周）。过期后运行 `bash browser-login.sh` 重新登录。日常在 Chrome 中偶尔访问小红书 + 每日 cookie 自动同步可延长有效期。
2. **QR 码登录已失效**：小红书改为扫码两次确认，MCP 的 `get_login_qrcode` 无法处理，必须用浏览器登录。
3. **正文字数限制**：小红书内部计数与 Python `len()` 有偏差（多约 3-5%），`publish.py` 限制 950 字（留余量）。超长自动截断。
4. **macOS TCC**：launchd 无法读写 `~/Documents/`，vault 放在 `~/xiaohongshu-mcp/vault/`，通过 symlink 给 Obsidian 访问。
5. **feed_id 获取延迟**：发布后立即搜索有时找不到，feedback.py 在 48h 内持续重试。
6. **MCP 单实例**：所有脚本共享同一 MCP server，通过端口检测避免重复启动。
7. **launchd PATH 受限**：launchd 环境无 `/usr/sbin`，已在 `start_mcp.sh`（使用 `nc` + `/usr/sbin/lsof` 完整路径）和 `run_publish.sh`（显式 export PATH）中修复。
8. **Claude Code 嵌套限制**：在 Claude Code 内手动运行 Python 调 LLM，需 `env -u CLAUDECODE python3 script.py`。
9. **内容生产需手动触发**：NotebookLM 问答流程需人工参与（Claude 提问 → 用户喂给 NotebookLM → Claude 改写）。待发布文章用完后需手动重复此循环。
10. **Cookie 同步限制**：`browser-login.sh` 使用 go-rod 临时 Chrome 实例（非 Profile 4），所以登录后 Chrome Profile 4 不会自动获得新 session。需用户在 Chrome 中手动访问一次小红书，daily sync 才能持续续命。
