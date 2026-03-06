#!/usr/bin/env python3
"""
小红书封面图生成器（本地 PIL）
支持两套模板：
  options  — 深色金融风，品牌「期权研究室」
  ai_tools — 渐变科技风，品牌「AI工具派」

尺寸：1080×1440（3:4 竖版）
"""

import hashlib
import re
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COVER_DIR = Path("/Users/jarvis/xiaohongshu-mcp/covers")
COVER_DIR.mkdir(exist_ok=True)

FONT_BOLD  = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_LIGHT = "/System/Library/Fonts/STHeiti Light.ttc"

W, H = 1080, 1440

# ─── 模板色彩配置 ─────────────────────────────────────────────────────────────
# options：深色渐变，金融感强
# (顶部色, 底部色, 强调色, 文字色)
OPTIONS_THEMES = [
    ((15,  55,  150), (8,   30,  90),  (80,  200, 255), (255, 255, 255)),  # 深蓝+青
    ((180, 20,  20),  (100, 8,   8),   (255, 220, 50),  (255, 255, 255)),  # 深红+金
    ((80,  20,  160), (40,  8,   90),  (255, 200, 80),  (255, 255, 255)),  # 深紫+金
    ((20,  100, 80),  (8,   55,  40),  (160, 255, 180), (255, 255, 255)),  # 墨绿+薄荷
    ((180, 80,  10),  (100, 40,  5),   (255, 240, 120), (255, 255, 255)),  # 深橙+黄
]

# ai_tools：浅色卡片风，科技感强（与 options 深色风形成强烈对比）
# (背景色, 头部色块, 强调色, 标题文字色, 要点框底色)
AI_TOOLS_THEMES = [
    ((248, 250, 255), (55,  125, 255), (55,  125, 255), (18,  20,  50),  (225, 237, 255)),  # 浅蓝+蓝
    ((255, 250, 246), (255,  95,  55), (255,  95,  55), (45,  18,   8),  (255, 235, 225)),  # 浅橙+橙
    ((252, 248, 255), (130,  55, 215), (130,  55, 215), (28,  12,  48),  (242, 232, 255)),  # 浅紫+紫
    ((244, 255, 250), ( 18, 165, 125), ( 18, 165, 125), ( 8,  38,  28),  (215, 255, 238)),  # 浅青+绿
    ((255, 246, 250), (215,  55, 120), (215,  55, 120), (45,   8,  22),  (255, 228, 242)),  # 浅玫+玫
]


# ─── 工具函数 ─────────────────────────────────────────────────────────────────
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _draw_gradient(img: Image.Image, top: tuple, bottom: tuple) -> None:
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def _line_h(font, text: str) -> int:
    try:
        bb = font.getbbox(text)
        return bb[3] - bb[1]
    except Exception:
        return font.size


def _wrap_text(draw: ImageDraw.Draw, text: str, font, fill,
               x: int, y: int, max_w: int, line_gap: int = 10) -> int:
    char_w = font.size
    chars_per = max(1, max_w // char_w)
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            continue
        if len(para) <= chars_per:
            lines.append(para)
        else:
            lines.extend(textwrap.wrap(para, width=chars_per))
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += _line_h(font, line) + line_gap
    return y


def extract_key_points(content: str, max_points: int = 3) -> list[str]:
    """从正文提取 2-3 个关键要点。"""
    points = []
    BLACKLIST = re.compile(
        r'^(适用|结果|操作|当前|经验公式|黄金法则|注意|例如|比如|举例|说明|\d+[%％元万].*$)'
    )

    def is_valid(s: str) -> bool:
        s = s.strip()
        if len(s) < 5 or len(s) > 16:
            return False
        if re.match(r'^[\d\s\-=→+]+$', s):
            return False
        if BLACKLIST.match(s):
            return False
        if s in points:
            return False
        return True

    def clean(s: str) -> str:
        s = re.sub(r'\*+', '', s)
        s = s.strip().lstrip('：:·・').rstrip('：:。')
        return s

    # 1. 优先取 ## 标题
    for _, m in re.findall(r'^(#{2,3})\s+(.+)$', content, re.MULTILINE):
        m = re.sub(r'^[❌✅⚠️💡🔥⚡️①②③④⑤]+\s*', '', m)
        m = re.sub(r'^\d+[\.、]\s*', '', m)
        m = clean(m)
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 2. 取 **粗体**
    LABEL_WORDS = re.compile(r'^(表现|为什么|正确做法|建议|注意|结果|操作|当前)')
    for m in re.findall(r'\*\*([^*]+)\*\*', content):
        m = clean(m)
        if LABEL_WORDS.match(m):
            continue
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 3. 兜底：① ② ③ 列表项 / 数字列表（[\.、] 可选，① 后直接接空格也能匹配）
    for m in re.findall(r'^[①②③④⑤\d][\.、]?\s+(.+)$', content, re.MULTILINE):
        m = clean(m)
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    return points[:max_points]


# ─── 模板 A：options 深色金融风 ───────────────────────────────────────────────
def _render_options(title: str, content: str, index: int) -> Image.Image:
    top_c, bot_c, accent, text_c = OPTIONS_THEMES[index % len(OPTIONS_THEMES)]

    img = Image.new("RGB", (W, H), top_c)
    _draw_gradient(img, top_c, bot_c)
    draw = ImageDraw.Draw(img)

    # 顶部暗条
    img.paste(Image.new("RGB", (W, 180), (0, 0, 0)), (0, 0),
              Image.new("L", (W, 180), 60))

    # 品牌
    brand_font = _font(FONT_LIGHT, 58)
    draw.text((72, 64), "期权研究室", font=brand_font, fill=(*accent, 255))
    draw.rectangle([72, 130, 320, 138], fill=accent)

    # 主标题
    clean_title = re.sub(
        r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s：:·\-—()（）【】%！!？?]', '', title
    ).strip()
    fs = 112 if len(clean_title) <= 10 else 96 if len(clean_title) <= 14 else 80
    title_font = _font(FONT_BOLD, fs)
    title_y = _wrap_text(draw, clean_title, title_font, text_c, 72, 430, W - 144, 18)
    title_y += 72

    # 装饰点
    for i in range(3):
        draw.ellipse([72 + i * 24, title_y, 84 + i * 24, title_y + 12], fill=accent)
    title_y += 48

    # 关键要点
    points = extract_key_points(content) if content else []
    if points:
        pt_font = _font(FONT_LIGHT, 62)
        for pt in points:
            pt_text = f">> {pt}"
            draw.text((72, title_y), pt_text, font=pt_font, fill=text_c)
            title_y += _line_h(pt_font, pt_text) + 34
    else:
        sub_font = _font(FONT_LIGHT, 66)
        draw.text((72, title_y), "美股期权深度分析", font=sub_font, fill=(*accent,))

    # 底部暗条 + slogan + 期数
    for y in range(H - 160, H):
        alpha = int(180 * (y - (H - 160)) / 160)
        r, g, b = max(0, top_c[0]-40), max(0, top_c[1]-40), max(0, top_c[2]-40)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    slogan_font = _font(FONT_LIGHT, 50)
    draw.text((72, H - 100), "美股 · 期权 · 财富自由",
              font=slogan_font, fill=(255, 255, 255, 180))
    num_font = _font(FONT_BOLD, 54)
    draw.text((W - 110, H - 98), f"#{index + 1:02d}", font=num_font, fill=accent)

    return img


# ─── 模板 B：ai_tools 浅色卡片风（与 options 深色金融风强烈对比）────────────
def _render_ai_tools(title: str, content: str, index: int) -> Image.Image:
    bg_c, header_c, accent, title_c, box_c = AI_TOOLS_THEMES[index % len(AI_TOOLS_THEMES)]

    # ── 浅色背景 ─────────────────────────────────────────
    img = Image.new("RGB", (W, H), bg_c)
    draw = ImageDraw.Draw(img)

    # ── 头部色块（实色，220px）────────────────────────────
    draw.rectangle([0, 0, W, 220], fill=header_c)

    # 品牌名（白色，大号）
    brand_font = _font(FONT_BOLD, 76)
    draw.text((72, 38), "AI工具派", font=brand_font, fill=(255, 255, 255))

    # 副标题（半透明白）
    tag_font = _font(FONT_LIGHT, 40)
    draw.text((72, 134), "发现好工具 · 效率加速 · 开箱即用",
              font=tag_font, fill=(255, 255, 255, 200))

    # 右上角期数徽标（白色圆角矩形 + 强调色文字）
    num_font = _font(FONT_BOLD, 42)
    num_str = f"#{index + 1:02d}"
    nb = num_font.getbbox(num_str)
    nw = nb[2] - nb[0] + 24
    nh = nb[3] - nb[1] + 16
    nx = W - 68 - nw
    ny = 52
    draw.rectangle([nx, ny, nx + nw, ny + nh], fill=(255, 255, 255))
    draw.text((nx + 12, ny + 8), num_str, font=num_font, fill=header_c)

    # ── 主标题（暗色，大字，左对齐）──────────────────────
    clean_title = re.sub(
        r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s：:·\-—()（）【】%！!？?]', '', title
    ).strip()
    fs = 110 if len(clean_title) <= 9 else 90 if len(clean_title) <= 13 else 76
    title_font = _font(FONT_BOLD, fs)
    title_y = _wrap_text(draw, clean_title, title_font, title_c, 72, 276, W - 120, 16)
    title_y += 52

    # ── 要点框（带左侧色条的浅色卡片）───────────────────
    points = extract_key_points(content) if content else []
    if points:
        pt_font = _font(FONT_LIGHT, 56)
        lh = _line_h(pt_font, "测")
        for i, pt in enumerate(points):
            box_h = lh + 44
            # 卡片底色
            draw.rectangle([72, title_y, W - 72, title_y + box_h], fill=box_c)
            # 左侧强调条（12px 宽）
            draw.rectangle([72, title_y, 84, title_y + box_h], fill=accent)
            # 序号（强调色）
            num_sym = ["①", "②", "③"][i] if i < 3 else "•"
            draw.text((104, title_y + 22), num_sym, font=pt_font, fill=accent)
            # 要点文字
            draw.text((104 + pt_font.size + 10, title_y + 22), pt,
                      font=pt_font, fill=title_c)
            title_y += box_h + 20
    else:
        sub_font = _font(FONT_LIGHT, 62)
        draw.text((72, title_y), "AI效率神器推荐", font=sub_font, fill=accent)

    # ── 底部实色条（accent 色，130px）────────────────────
    draw.rectangle([0, H - 130, W, H], fill=accent)

    # 底部 slogan（白色）
    slogan_font = _font(FONT_LIGHT, 48)
    draw.text((72, H - 98), "AI工具 · 效率飞升 · 开箱即用",
              font=slogan_font, fill=(255, 255, 255))

    # 底部右侧小装饰：3 个白色圆点
    for i in range(3):
        cx = W - 100 - i * 32
        cy = H - 66
        draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(255, 255, 255, 180))

    return img


# ─── 对外接口 ─────────────────────────────────────────────────────────────────
def generate_cover(title: str, content: str = "",
                   index: int = 0, category: str = "options") -> str:
    """
    生成封面图，返回本地文件绝对路径。
    相同参数命中缓存直接返回。

    category: "options"   → 深色金融风（期权研究室）
              "ai_tools"  → 渐变科技风（AI工具派）
              其他值       → 按 options 处理
    """
    cache_key = hashlib.md5(
        f"{category}{title}{content[:200]}".encode()
    ).hexdigest()[:10]
    out_path = COVER_DIR / f"cover_{cache_key}.jpg"
    if out_path.exists():
        return str(out_path)

    if category == "ai_tools":
        img = _render_ai_tools(title, content, index)
    else:
        img = _render_options(title, content, index)

    img.save(str(out_path), "JPEG", quality=93)
    return str(out_path)


if __name__ == "__main__":
    import subprocess

    # 测试 options 模板
    path1 = generate_cover(
        "LEAPS期权怎么选执行价",
        "**至少选1年后到期**\n## 第一步：排除虚值\n## 第二步：看成本比率\n成本比率 < 15% 才值得买",
        index=0, category="options",
    )
    print(f"options 封面: {path1}")
    subprocess.run(["open", path1])

    # 测试 ai_tools 模板
    path2 = generate_cover(
        "NotebookLM读论文只要10分钟",
        "① 上传PDF直接问问题\n② 自动生成播客摘要\n③ 多文档交叉检索",
        index=2, category="ai_tools",
    )
    print(f"ai_tools 封面: {path2}")
    subprocess.run(["open", path2])
