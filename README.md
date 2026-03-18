# xiaohongshu-bot

> 一个面向多账号的小红书自动化内容运营系统。从选题、写作、封面生成到定时发布，全流程自动化；通过互动数据反馈持续优化内容质量。

---

## 目录

- [项目概览](#项目概览)
- [账号体系](#账号体系)
- [目录结构](#目录结构)
- [核心架构](#核心架构)
  - [内容生产流水线](#内容生产流水线)
  - [MCP 发布层](#mcp-发布层)
  - [反馈进化循环](#反馈进化循环)
- [期权账号（xhs-option）](#期权账号xhs-option)
- [宇宙能量账号（xhs-energy）](#宇宙能量账号xhs-energy)
- [共享模块（shared/）](#共享模块shared)
- [定时任务体系](#定时任务体系)
- [配置说明](#配置说明)
- [快速上手](#快速上手)
- [登录与 Cookie 管理](#登录与-cookie-管理)
- [Claude Code Skills](#claude-code-skills)
- [依赖与环境](#依赖与环境)

---

## 项目概览

本项目是一个 **macOS + launchd** 驱动的小红书多账号自动发布系统，核心设计理念：

| 目标 | 实现方式 |
|---|---|
| **账号安全隔离** | 每账号独立 MCP server、独立 Chrome Profile、独立 cookies.json |
| **内容质量** | NotebookLM 书籍知识库 + 多平台素材采集 + Claude 深度改编 |
| **自动进化** | 发布后拉取互动数据 → 主题权重反馈 → 下次选题优先高分主题 |
| **路径可移植** | 所有路径通过 `Path(__file__).parent` 或 `accounts.json` 动态推导，无硬编码用户名 |

---

## 账号体系

| 账号 | 小红书昵称 | 内容方向 | 发布频率 | MCP 端口 | Chrome Profile |
|---|---|---|---|---|---|
| `xhs-option` | wick123 | 美股期权教育 | 2 篇/天（09:30 / 21:30） | 18060 | Profile 5 |
| `xhs-energy` | SS心灵疗愈所 | 宇宙能量 / 显化 / 吸引力法则 | 3 篇/天（10:18 / 14:18 / 22:18） | 18061 | Profile 4 |

账号配置集中管理于根目录 [`accounts.json`](accounts.json)。

---

## 目录结构

```
xiaohongshu-bot/
├── accounts.json                  # 账号注册表（单一事实来源）
├── shared/
│   ├── config.py                  # 路径推导中心（PROJECT_ROOT / get_account）
│   ├── feedback.py                # 互动数据反馈脚本（两账号合一）
│   └── com.jarvis.xhs-feedback.plist  # launchd plist（每天 02:00）
│
├── xhs-option/                    # 期权账号
│   ├── publish.py                 # 定时发布主脚本
│   ├── research.py                # Track A 内容生产脚本
│   ├── make_cover.py              # 封面图生成器（4 套模板）
│   ├── llm.py                     # Claude CLI 调用封装
│   ├── collectors.py              # 多平台素材采集（XHS / YouTube / Twitter / Reddit / RSS）
│   ├── trend_scout.py             # 选题调研脚本（趋势分析）
│   ├── notebooklm_sync.py         # NotebookLM 知识库半自动同步
│   ├── topics.json                # 主题池配置
│   ├── knowledge_base/            # 期权书籍精华（按主题分文件）
│   │   ├── options_basics.md
│   │   ├── greeks_explained.md
│   │   ├── strategy_playbook.md
│   │   ├── leaps_guide.md
│   │   ├── risk_and_mindset.md
│   │   ├── options_vs_stocks.md
│   │   └── earnings_and_events.md
│   ├── pipeline/
│   │   ├── track_a/               # 期权知识深度改编流水线
│   │   │   ├── writer.py          # 文章生成器（LLM 深度改编）
│   │   │   ├── curator.py         # 每周精选英文教育素材
│   │   │   └── knowledge.py       # 书籍知识库加载器
│   │   └── track_b/               # AI 工具热帖翻译流水线
│   │       ├── scanner.py         # Twitter/Reddit 热帖扫描
│   │       └── translator.py      # 热帖 → 小红书笔记
│   ├── vault/
│   │   ├── 待发布/                 # 待发布文章（Markdown）
│   │   ├── 待审核/                 # 自动生成待人工审核的文章
│   │   └── 已发布/                 # 已发布归档（含互动数据追踪表格）
│   ├── state/
│   │   ├── theme_weights.json     # 主题权重（feedback.py 更新）
│   │   └── content_plan.json      # trend_scout 输出的选题计划
│   ├── covers/                    # 生成的封面图缓存（按内容哈希命名）
│   ├── published.json             # 发布状态 + 互动数据检查点
│   ├── sync_cookies_from_chrome.py
│   ├── start_mcp.sh
│   ├── browser-login.sh
│   ├── run_publish.sh
│   ├── xiaohongshu-mcp-darwin-arm64   # MCP server 二进制
│   ├── xiaohongshu-login-darwin-arm64 # 登录工具二进制
│   ├── launchd/                   # launchd plist 文件（未安装版本）
│   └── skills/xhs-option/         # Claude Code Skill
│       ├── SKILL.md               # 精简执行手册（~80行）
│       └── SKILL-GUIDE.md         # 完整参考手册（备份）
│
└── xhs-energy/                    # 宇宙能量账号
    ├── publish.py
    ├── make_cover.py              # 封面生成器（照片底图 + 思源宋体）
    ├── sync_cookies_yuzhou.py
    ├── start_mcp.sh
    ├── fonts/                     # 内嵌字体
    │   ├── SourceHanSerifCN-Regular.ttf
    │   ├── LXGWWenKai-Regular.ttf
    │   └── ZhuqueFangsong-Regular.ttf
    ├── backgrounds/               # 封面底图（jpg/png，自动循环）
    ├── published.json
    ├── xiaohongshu-mcp-darwin-arm64
    ├── xiaohongshu-login-darwin-arm64
    └── skills/xhs-energy/
        ├── SKILL.md
        └── SKILL-GUIDE.md
```

---

## 核心架构

### 内容生产流水线

```
┌─────────────────────────────────────────────────────────────────┐
│                        内容生产（xhs-option）                     │
│                                                                  │
│  NotebookLM 知识库          多平台素材采集                         │
│  knowledge_base/*.md  ──►  collectors.py                         │
│  (Cottle / Sinclair /       (XHS / YouTube /                     │
│   Cordier 等经典书籍)        Twitter / Reddit / RSS)              │
│          │                        │                              │
│          └──────────┬─────────────┘                              │
│                     ▼                                            │
│              pipeline/track_a/writer.py                          │
│              (Claude LLM 深度改编，非翻译)                         │
│                     │                                            │
│                     ▼                                            │
│              vault/待审核/    ◄── 人工 approve                    │
│                     │                                            │
│                     ▼                                            │
│              vault/待发布/                                        │
└─────────────────────────────────────────────────────────────────┘

Track B（AI工具）：
  scanner.py → Twitter/Reddit 热帖 → translator.py → vault/待发布/
```

**Track A** 特点：从经典期权书籍 + 英文教育账号素材中吸收知识，用 Claude 以「懂行的朋友聊天」风格重新创作，**不是翻译**。写作红线包括禁用词检测、结构过度检测（≥3个`##`标题报警）、字数超限自动修复。

**Track B** 特点：扫描 Twitter/Reddit 当日热帖，按「互动量 × 时效性」打分，Top N 条翻译为小红书格式。

---

### MCP 发布层

每个账号独立运行一个 `xiaohongshu-mcp-darwin-arm64` HTTP 服务：

```
Claude Code / publish.py
        │
        │  JSON-RPC over HTTP
        ▼
xhs-option MCP server (port 18060)  ──►  小红书账号 wick123
xhs-energy MCP server (port 18061)  ──►  小红书账号 SS心灵疗愈所
```

**账号安全机制**：
- MCP 工具名前缀强制绑定：`mcp__xhs-option__*` 只能调用 18060，不能误触 18061
- `publish.py` 发布前校验 `cookies.json` 中的 `customerClientId`，不匹配则拒绝发布
- Chrome Profile 物理隔离：期权用 Profile 5，宇宙能量用 Profile 4

---

### 反馈进化循环

```
发布成功
    │
    ▼
search_feeds → 获取 feed_id（发布后15秒）
    │
    ▼
published.json 记录 {feed_id, checkpoints: {}}
    │
    ▼  （launchd 每天 02:00 触发 shared/feedback.py）
    │
    ├── 拉取 get_feed_detail 互动数据
    │   时间节点：30min / 1h / 3h / 6h / 24h / 3天 / 7天 / 14天
    │
    ├── 写回 published.json checkpoints
    ├── 写入 vault/已发布/*.md 数据追踪表格
    ├── 生成 AI 复盘（Claude 2-3句点评）
    │
    ├── 更新 state/theme_weights.json
    │   engagement_score = collected×3 + liked×1 + comment×2 + shared×2
    │   高分主题权重提升 → research.py 优先生产
    │
    └── 生成 shared/perf.json
        → writer.py 注入历史 top3/bottom3 → 影响下一篇内容方向
```

---

## 期权账号（xhs-option）

### 内容方向

美股期权教育，目标读者：有一定基础的散户投资者。

**主题池**（`topics.json`，共 11 个主题）：

| 主题 ID | 名称 |
|---|---|
| `options_basics` | 期权入门概念 |
| `greeks_explained` | 希腊字母实战解读 |
| `strategy_playbook` | 期权策略图鉴 |
| `leaps_guide` | LEAPS 长期期权入门 |
| `risk_and_mindset` | 风控与交易心态 |
| `options_vs_stocks` | 期权 vs 股票 |
| `earnings_and_events` | 财报与事件驱动 |
| *(+ AI工具 4个)* | NotebookLM / Claude Code 等 |

### 写作规范

- 正文 ≤ 950 字（XHS 内部计数有偏差，宽松上限 1000）
- 风格：「懂行的朋友在咖啡馆聊期权」，不是教科书
- 允许 1-2 段 bullet list，禁止 ≥3 个 `##` 二级标题
- **禁用词**：「简单来说」「值得注意的是」「总的来说」「首先…其次…最后」「不得不说」「相信很多人」

### 封面图模板（`make_cover.py`）

| 模板 | 适用场景 | 风格 |
|---|---|---|
| `options` | 期权教育类 | 深色渐变金融风，品牌「期权研究室」，12 色循环 |
| `ai_tools` | AI 工具类 | 浅色卡片科技风，品牌「AI工具派」，12 色循环 |
| `pa` | Price Action 系列 | 深色高级感，圆角标签栏 + 美元图，6 色循环 |
| `broad_finance` | 泛财经系列 | 白底斜纹 + 美元撕纸图 + 绿色边框，品牌「美股研习社」 |

封面图按内容 MD5 缓存，相同标题+内容直接复用。

### 知识库（`knowledge_base/`）

每个主题对应一个 Markdown 文件，存放从 NotebookLM 提炼的书籍精华。
知识库内容在 prompt 中作为**最高权威来源**，优先于实时采集素材。

填充方式：
1. 打开 NotebookLM，切换到期权书籍笔记本（Cottle / Sinclair / Cordier 等）
2. 针对主题提问，将回答整理后粘贴到 `knowledge_base/<theme_id>.md`
3. 或运行 `python notebooklm_sync.py` 半自动同步

---

## 宇宙能量账号（xhs-energy）

### 内容方向

宇宙能量 / 吸引力法则 / 显化 / 冥想 / 潜意识，目标读者：25-35 岁女性。

### 写作规范（fiya 风格）

- 正文 300-450 字（不超 450 字）
- 用 `·` 分节，**禁止**粗体、emoji 列表、命令式语气
- 必须以日记感开场（「今天想和你分享…」/「刚刚有个想法…」）
- 结尾必须有福气钩子（「刷到这篇的人…」/「留言的人…」）
- 无粗体，无二级标题

### 封面图（`make_cover.py`）

- **有底图模式**：`backgrounds/` 目录下的照片作为底图，叠加思源宋体中文标题 + 白色描边
- **纯渐变 fallback**：无底图时使用柔和渐变 + 光晕效果（8 套配色）
- 底图按标题哈希固定选取，同一文章始终用同一张背景

**注意**：宇宙能量封面为纯底图，**不叠加文字卡片**（与期权账号风格的核心区别）。

### Vault 位置

宇宙能量的 vault 在 repo 外（`~/Documents/宇宙能量/`），方便与 Obsidian 同步。
路径通过 `accounts.json` 配置，`publish.py` 在运行时读取。

---

## 共享模块（shared/）

### `config.py`

项目路径推导中心，所有脚本通过此模块获取配置，消除硬编码路径：

```python
from shared.config import PROJECT_ROOT, get_account

# PROJECT_ROOT 自动推导为 monorepo 根目录
log_file = PROJECT_ROOT / "xhs-option/logs/feedback.log"

# get_account 返回账号配置，路径字段自动展开为绝对路径
cfg = get_account("xhs-energy")
vault_dir = Path(cfg["vault_pending"])   # /Users/.../Documents/宇宙能量/待发布
```

路径解析规则：
- 以 `/` 开头 → 原样返回（外部绝对路径，如 energy vault）
- 其他 → 相对于 `PROJECT_ROOT` 展开

### `feedback.py`

两账号共用的互动数据反馈脚本，每天 02:00 由 launchd 触发。

**核心功能**：
1. 对已发布文章，按 8 个时间节点拉取互动数据（30min → 14天）
2. 对 feed_id 缺失的条目（发布后 48h 内），重试搜索
3. 将数据写回 `published.json` checkpoints 字段
4. 在 Obsidian vault md 文件末尾追加数据追踪表格
5. 触发 Claude AI 复盘（≥6h 数据可用时，写 2-3 句分析）
6. 更新 `state/theme_weights.json`（主题得分归一化）
7. 生成 `shared/perf.json`（供 writer.py 的历史表现注入）

---

## 定时任务体系

所有定时任务由 macOS launchd 管理（安装位置：`~/Library/LaunchAgents/`）。

### 期权账号

| 任务 | 时间 | 脚本 |
|---|---|---|
| MCP server 保活 | 开机启动 | `xhs-option/start_mcp.sh` |
| 早间发布 | 09:30 | `xhs-option/publish.py` |
| 晚间发布 | 21:30 | `xhs-option/publish.py` |
| Track B 热帖扫描 | 每日 | `pipeline/track_b/scanner.py` |
| Track B 翻译 | 每日 | `pipeline/track_b/translator.py` |
| 周精选素材（curator） | 每周日 07:00 | `pipeline/track_a/curator.py` |
| Cookie 同步（Chrome Profile 5） | 每日 03:00 | `sync_cookies_from_chrome.py` |

### 宇宙能量账号

| 任务 | 时间 | 脚本 |
|---|---|---|
| MCP server 保活 | 开机启动 | `xhs-energy/start_mcp.sh` |
| 发布（×3） | 10:18 / 14:18 / 22:18 | `xhs-energy/publish.py` |
| Cookie 同步（Chrome Profile 4） | 每日 03:05 | `sync_cookies_yuzhou.py` |

### 共享任务

| 任务 | 时间 | 脚本 |
|---|---|---|
| 互动数据反馈 | 每日 02:00 | `shared/feedback.py` |

---

## 配置说明

### `accounts.json`

所有账号参数的单一事实来源。内部路径用相对路径（相对 PROJECT_ROOT），外部路径用绝对路径：

```json
{
  "accounts": {
    "xhs-option": {
      "display_name": "wick123",
      "port": 18060,
      "chrome_profile": "Profile 5",
      "vault_pending": "xhs-option/vault/待发布",      // 相对路径 → 自动展开
      "vault_published": "xhs-option/vault/已发布",
      "publish_times": ["09:30", "21:30"],
      "max_chars": 950,
      "expected_login_name": "wick123"
    },
    "xhs-energy": {
      "display_name": "SS心灵疗愈所",
      "port": 18061,
      "chrome_profile": "Profile 4",
      "vault_pending": "/Users/.../Documents/宇宙能量/待发布",  // 绝对路径 → 原样使用
      "vault_published": "/Users/.../Documents/宇宙能量/已发布",
      "publish_times": ["10:18", "14:18", "22:18"],
      "max_chars": 450
    }
  }
}
```

**换机器时只需修改**：`xhs-energy` 的 `vault_pending` / `vault_published`（如果 Documents 路径不同）。

### MCP server 配置（`~/.claude.json`）

```json
{
  "mcpServers": {
    "xhs-option": {
      "type": "http",
      "url": "http://localhost:18060/mcp"
    },
    "xhs-energy": {
      "type": "http",
      "url": "http://localhost:18061/mcp"
    }
  }
}
```

工具前缀由 key 名决定：`xhs-option` → `mcp__xhs-option__publish_content`，物理隔离两账号。

---

## 快速上手

### 环境要求

- macOS（launchd 定时任务依赖 macOS 系统）
- Python 3.10+
- Google Chrome（Period 账号登录）
- `pip install pillow`（封面图生成）
- `pip install pycookiecheat`（Cookie 同步，需在 venv 中）
- Claude CLI（`npm install -g @anthropic-ai/claude-code`，LLM 调用）

### 首次部署

```bash
# 1. 克隆仓库
git clone https://github.com/bradstan/xiaohongshu-bot.git
cd xiaohongshu-bot

# 2. 修改 vault 路径（energy 账号 vault 在 repo 外）
vim accounts.json
# 更新 xhs-energy.vault_pending / vault_published 为你的路径

# 3. 创建 venv 并安装依赖
python3 -m venv xhs-option/venv && xhs-option/venv/bin/pip install pycookiecheat pillow
python3 -m venv xhs-energy/venv && xhs-energy/venv/bin/pip install pillow

# 4. 配置 MCP server（~/.claude.json）
# 参考上方「MCP server 配置」章节

# 5. 登录小红书账号
cd xhs-option && bash browser-login.sh      # 扫码两次登录 wick123
cd xhs-energy && bash browser-login.sh      # 扫码两次登录 SS心灵疗愈所

# 6. 启动 MCP server
bash xhs-option/start_mcp.sh
bash xhs-energy/start_mcp.sh

# 7. 安装 launchd 定时任务（以发布任务为例）
cp xhs-option/launchd/*.plist ~/Library/LaunchAgents/
cp xhs-energy/launchd/*.plist ~/Library/LaunchAgents/
cp shared/com.jarvis.xhs-feedback.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jarvis.xhs-publish-morning.plist
# （对所有 plist 重复此操作）
```

### 手动发布

```bash
# 期权账号
/usr/bin/python3 xhs-option/publish.py

# 宇宙能量账号
xhs-energy/venv/bin/python3 xhs-energy/publish.py
```

### 手动触发内容生产

```bash
# 生成 5 篇期权文章（写入待审核/）
cd xhs-option && python3 research.py

# 强制生成指定篇数
python3 research.py --count 3

# 手动运行反馈脚本
/usr/bin/python3 shared/feedback.py
```

### 检查 MCP server 状态

```bash
nc -z 127.0.0.1 18060 && echo "xhs-option OK" || echo "xhs-option DOWN"
nc -z 127.0.0.1 18061 && echo "xhs-energy OK" || echo "xhs-energy DOWN"
```

---

## 登录与 Cookie 管理

小红书登录需要**扫码两次**（第一次登录，第二次确认），普通的二维码接口已失效。

### 登录流程

```bash
# 期权账号（Chrome Profile 5）
cd xhs-option
./xiaohongshu-login-darwin-arm64 -bin "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# → 浏览器打开，扫码两次 → 完成后运行：
bash start_mcp.sh
```

### Cookie 自动同步

登录后 Cookie 会随时间过期。每天 03:00 launchd 自动同步 Chrome 中的最新 session：

- **期权**：`sync_cookies_from_chrome.py`（Profile 5）
- **宇宙能量**：`sync_cookies_yuzhou.py`（Profile 4）

同步逻辑：比较 `web_session` token 新鲜度，仅在 Chrome 有更新时才同步，避免覆盖刚刚手动登录的 cookies。

### 发布失败排查

```
isError=true → 检查登录状态 → 重新登录
MCP 超时 → nc -z 127.0.0.1 18060 → bash start_mcp.sh
```

---

## Claude Code Skills

本项目提供两个 Claude Code Skill，用于在 Claude 会话中手动发布内容：

### xhs-option Skill

位置：`xhs-option/skills/xhs-option/SKILL.md`

功能：完整的期权账号发布工作流——
1. 验证登录（`mcp__xhs-option__check_login_status`，必须返回「wick123」）
2. 写文章（300-950 字，朋友聊天风格，遵循禁用词清单）
3. 生成封面（`make_cover.py` 或 `qiaomu-mondo-poster-design`）
4. 呈现草稿等待用户审核
5. 发布（`mcp__xhs-option__publish_content`）
6. 归档到 `vault/待发布/YYYY-MM-DD｜标题.md`

### xhs-energy Skill

位置：`xhs-energy/skills/xhs-energy/SKILL.md`

功能：宇宙能量账号发布工作流——
与 option 流程相同，风格要求完全不同：fiya 日记感、`·` 分节、无粗体、300-450 字、结尾福气钩子。

### 安全机制

两个 Skill 的第一步都是 `check_login_status` 并验证返回的账号名称，**不得跳过**。防止使用错误账号的工具前缀发布内容。

---

## 依赖与环境

### Python 包

```
pillow          # 封面图生成（PIL）
pycookiecheat   # Chrome Cookie 提取（需在 venv 中安装）
```

### 外部工具

| 工具 | 用途 | 安装方式 |
|---|---|---|
| `claude` CLI | LLM 调用（writer.py / feedback.py AI 复盘） | `npm install -g @anthropic-ai/claude-code` |
| `agent-reach` | Twitter / Reddit 内容采集 | 私有工具，需单独配置 |
| `xiaohongshu-mcp-darwin-arm64` | XHS MCP server 二进制 | 已包含在各子目录 |
| `xiaohongshu-login-darwin-arm64` | 浏览器扫码登录工具 | 已包含在各子目录 |

### 系统字体（macOS 内置）

| 字体 | 用途 |
|---|---|
| `/System/Library/Fonts/STHeiti Medium.ttc` | 期权封面主标题 |
| `/System/Library/Fonts/STHeiti Light.ttc` | 期权封面副文本 / 品牌名 |

### 内嵌字体（`xhs-energy/fonts/`）

| 字体 | 用途 |
|---|---|
| `SourceHanSerifCN-Regular.ttf` | 宇宙能量封面主标题（思源宋体） |
| `LXGWWenKai-Regular.ttf` | 备用文艺风格 |
| `ZhuqueFangsong-Regular.ttf` | 备用仿宋风格 |

---

## 常见问题

**Q: 发布后互动数据为什么要等几天才有数据？**
A: `feedback.py` 每天 02:00 运行，7 天以内的 checkpoint 会在对应时间点到达后自动填充。14 天数据（长尾效果）最有参考价值。

**Q: 如何手动触发互动数据拉取？**
```bash
/usr/bin/python3 shared/feedback.py
```

**Q: writer.py 提示「暂无历史数据」？**
A: 需要至少一篇文章有 3 天以上的 checkpoint 数据，`shared/perf.json` 才会被 writer.py 注入历史表现。

**Q: 期权账号的 Claude Code Skill 用的是哪个 MCP server？**
A: `~/.claude.json` 中 `"xhs-option"` key 对应 port 18060，工具前缀 `mcp__xhs-option__*` 物理隔离，不会误用宇宙能量的 server。

**Q: 如何新增第三个账号？**
A: 在 `accounts.json` 新增账号条目 → 配置独立 MCP server 端口 → 在 `~/.claude.json` 注册 → 新建子目录（`xhs-xxx/`）复制 publish.py + make_cover.py → 在 `shared/feedback.py` 的 `ACCOUNTS` 列表追加配置。

---

*macOS only · Python 3.10+ · launchd scheduling · XHS MCP binary required*
