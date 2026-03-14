## 项目：小红书Bot —— 第二账号

- 项目目录：`/Users/jarvis/xiaohongshu-yuzhou/`
- 账号名：**SS复古审美**（当前名，计划后续改名为"将宇宙能量"）
- 核心脚本：`publish.py`（定时发布）、`make_cover.py`（封面图）、`mark_published.py`（标记已发）
- Vault（Obsidian）：`/Users/jarvis/Documents/宇宙能量/`
  - 待发布文件夹：`宇宙能量/待发布/`（publish.py 读取此处）
  - 已发布文件夹：`宇宙能量/已发布/`（发布后自动移入）
  - 待审核文件夹：`宇宙能量/待审核/`
  - 模板文件夹：`宇宙能量/模板/`
- 发布状态追踪：`published.json`
- 定时任务入口：`run_publish.sh`
- MCP server：`xiaohongshu-mcp-darwin-arm64`，监听 `http://localhost:18061/mcp`（端口 18061，与 wick123 的 18060 隔离）

### 与 wick123 账号的隔离清单

| 维度 | wick123 | 将宇宙能量 |
|------|---------|-----------|
| 目录 | `~/xiaohongshu-mcp/` | `~/xiaohongshu-yuzhou/` |
| MCP 端口 | 18060 | **18061** |
| Cookie 文件 | `mcp/cookies.json` | `yuzhou/cookies.json` |
| 定时发布时间 | 19:00 | **20:00** |

### 登录

- **必须用浏览器登录**：`bash browser-login.sh`（Chrome 窗口中登录【将宇宙能量】账号，非 wick123！）
- **NEVER use `get_login_qrcode`** — 小红书改了登录流程，该工具已失效
- Cookie 文件：`/Users/jarvis/xiaohongshu-yuzhou/cookies.json`

### 启动 MCP Server

```bash
bash ~/xiaohongshu-yuzhou/start_mcp.sh
# 或直接运行：
cd ~/xiaohongshu-yuzhou && ./xiaohongshu-mcp-darwin-arm64 -port :18061 -headless=true
```

### launchd 服务（需手动安装）

```bash
# MCP server 常驻服务
cp ~/xiaohongshu-yuzhou/launchd/com.jarvis.yuzhou-mcp-server.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jarvis.yuzhou-mcp-server.plist

# 每日 20:00 发布
cp ~/xiaohongshu-yuzhou/launchd/com.jarvis.yuzhou-publish-daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jarvis.yuzhou-publish-daily.plist
```

### 关键参数

- 正文字数上限：950 字（XHS 限制 1000，内部计数有偏差）
- `publish_content` 超时：150s
- MCP URL：`http://localhost:18061/mcp`

### 内容方向

**账号定位**：宇宙能量 / 心理 / 显化 / 潜意识编程 / mindset 升级

**NotebookLM 知识库**：`https://notebooklm.google.com/notebook/9767acca-571e-45c4-994a-c3da0c30d03e`（名称：能量与mindset）

知识库包含：
- **书籍**（pasted text）：
  - *As a Man Thinketh*（James Allen，7章）
  - *Becoming Supernatural*（Joe Dispenza，28章）
  - *Breaking The Habit of Being Yourself*（Joe Dispenza，5章）
  - *The Power of Your Subconscious Mind*（Joseph Murphy，18章）
  - *秘密全集 世界上最神奇的潜能开发训练*（The Secret 中文版，3章）
- **YouTube 视频**（100+条）：显化、吸引力法则、量子思维、身份升级、潜意识编程、影子工作、能量/频率

**内容生产流程**（与 wick123 Track A 类似）：
1. Claude 基于知识库主题生成 7 个问题
2. 用户喂给 NotebookLM（`notebooklm ask` 或 web UI）
3. NotebookLM 用书籍+视频内容回答
4. Claude 将回答改写为小红书长文（~850字）→ `Documents/宇宙能量/待发布/`
5. 每日 20:00 自动发布

**主题方向**（参考）：潜意识的力量、显化的原理与实操、能量频率与吸引力、打破旧身份/旧习惯、量子跳跃/平行现实、冥想与内在改变、自我认知升级

**风格标杆账号**：
- `-fiya`（ID: 5fe953810000000001003725）：文学感、内省、散文风，长句，不用夸张感叹号；**唯一参考对象**

**写作风格要点（仿 fiya）**：
- 开篇：提问句或反常识陈述，带读者进入思考
- 行文：段落短、留白多、语气温柔而有力
- 结尾：2句柔和祝福语，非"刷到就是信号"此类直白话术
- 封面图：照片底图 + 衬线字体白色大字 + 品牌"将 宇 宙 能 量"（`make_cover.py` yuzhou 模板）

**封面图系统（`make_cover.py`）**：
- 底图目录：`~/xiaohongshu-yuzhou/backgrounds/`（jpg/png 自动循环）
- 字体目录：`~/xiaohongshu-yuzhou/fonts/`
  - `LXGWWenKai-Regular.ttf`（霞鹜文楷，书写感）
  - `SourceHanSerifCN-Regular.ttf`（思源宋体，专业衬线）
  - `ZhuqueFangsong-Regular.ttf`（朱雀仿宋，古典仿宋）
  - 系统明朝体：`/System/Library/Fonts/ヒラギノ明朝 ProN.ttc`
- **当前用字体：`SourceHanSerifCN-Regular.ttf`（思源宋体）**
- 换字体：改 `make_cover.py` 顶部 `FONT_TITLE` 常量即可
- 有底图模式：照片 → 28%黑色柔化 → 白色标题（高斯阴影）→ 品牌字（半透明胶囊）
- 无底图 fallback：柔和渐变 + 光晕 + 深色标题

**话题标签策略**：
主标签：#宇宙能量 #显化 #吸引力法则 #潜意识 #能量提升 #高磁场高能量
辅标签：#自我成长 #女性成长 #mindset #觉醒 #内在成长 #高频率能量
蹭热标签：#高能量 #自我提升 #人生的意义
