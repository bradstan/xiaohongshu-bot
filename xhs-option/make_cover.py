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

COVER_DIR = Path(__file__).parent / "covers"
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
    ((20,  20,  120), (8,   8,   60),  (255, 215, 0),   (255, 255, 255)),  # 午夜蓝+纯金
    ((30,  30,  35),  (10,  10,  12),  (220, 180, 60),  (255, 255, 255)),  # 炭黑+深金
    ((50,  10,  120), (25,  5,   70),  (0,   230, 200), (255, 255, 255)),  # 电紫+青绿
    ((150, 15,  80),  (80,  8,   40),  (255, 200, 100), (255, 255, 255)),  # 深玫+香槟
    ((50,  70,  10),  (25,  40,  5),   (200, 255, 80),  (255, 255, 255)),  # 军绿+荧光
    ((30,  50,  90),  (15,  25,  55),  (200, 225, 255), (255, 255, 255)),  # 钢蓝+冰白
    ((100, 40,  10),  (55,  20,  5),   (255, 165, 50),  (255, 255, 255)),  # 深棕+琥珀
]

# pa：深色高级风，Price Action 系列教程
# (背景色, 边框色, 强调色/标题色, 文字色)
PA_THEMES = [
    ((18,  22,  42),  (55,  100, 220), (75,  140, 255), (255, 255, 255)),  # 深海军蓝+蓝
    ((18,  32,  30),  (50,  140, 120), (80,  185, 155), (255, 255, 255)),  # 深墨绿+青绿
    ((25,  15,  40),  (100, 55,  180), (140, 90,  220), (255, 255, 255)),  # 深紫+亮紫
    ((35,  15,  20),  (170, 55,  75),  (210, 80,  100), (255, 255, 255)),  # 深酒红+玫红
    ((30,  28,  22),  (180, 145, 50),  (220, 180, 70),  (255, 255, 255)),  # 深炭+金
    ((18,  28,  45),  (60,  150, 200), (90,  180, 230), (255, 255, 255)),  # 深钢蓝+冰蓝
]

# ai_tools：浅色卡片风，科技感强（与 options 深色风形成强烈对比）
# (背景色, 头部色块, 强调色, 标题文字色, 要点框底色)
AI_TOOLS_THEMES = [
    ((248, 250, 255), ( 55, 125, 255), ( 55, 125, 255), (18,  20,  50),  (225, 237, 255)),  # 浅蓝+蓝
    ((255, 250, 246), (255,  95,  55), (255,  95,  55), (45,  18,   8),  (255, 235, 225)),  # 浅橙+橙
    ((252, 248, 255), (130,  55, 215), (130,  55, 215), (28,  12,  48),  (242, 232, 255)),  # 浅紫+紫
    ((244, 255, 250), ( 18, 165, 125), ( 18, 165, 125), ( 8,  38,  28),  (215, 255, 238)),  # 浅青+绿
    ((255, 246, 250), (215,  55, 120), (215,  55, 120), (45,   8,  22),  (255, 228, 242)),  # 浅玫+玫
    ((255, 252, 240), (210, 140,   0), (210, 140,   0), (45,  28,   5),  (255, 240, 200)),  # 浅黄+琥珀
    ((245, 247, 252), ( 35,  55, 120), ( 35,  55, 120), (15,  20,  55),  (220, 228, 255)),  # 浅灰+深海蓝
    ((240, 255, 248), (  0, 130,  85), (  0, 130,  85), ( 5,  35,  22),  (200, 245, 225)),  # 浅薄荷+祖母绿
    ((255, 245, 242), (195,  45,  35), (195,  45,  35), (50,  10,   8),  (255, 218, 215)),  # 浅珊瑚+深红
    ((255, 250, 242), (130,  80,  30), (130,  80,  30), (40,  22,   8),  (245, 230, 205)),  # 浅米+深棕
    ((248, 246, 255), ( 75,  40, 180), ( 75,  40, 180), (22,  12,  55),  (230, 222, 255)),  # 浅薰衣草+深靛
    ((242, 252, 255), (  0, 150, 185), (  0, 150, 185), ( 5,  35,  45),  (205, 240, 252)),  # 浅天蓝+深青
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
    """从正文提取 2-3 个关键要点，用于封面图展示。"""
    points = []
    BLACKLIST = re.compile(
        r'^(适用|结果|操作|当前|经验公式|黄金法则|注意|例如|比如|举例|说明|\d+[%％元万].*$)'
    )

    def is_valid(s: str) -> bool:
        s = s.strip()
        if len(s) < 4 or len(s) > 16:
            return False
        if re.match(r'^[\d\s\-=→+]+$', s):
            return False
        if BLACKLIST.match(s):
            return False
        # 完全相同 or 子串重复
        for p in points:
            if s in p or p in s:
                return False
        return True

    def clean(s: str) -> str:
        s = re.sub(r'\*+', '', s)
        s = re.sub(r'["""]', '', s)           # 去引号，封面不需要
        s = s.strip().lstrip('：:·・').rstrip('：:。')
        return s

    def truncate_to_phrase(s: str, max_len: int = 16) -> str:
        """截取第一个短句作为要点，选最早的有效分隔点。"""
        s = s.strip()
        if len(s) <= max_len:
            return s
        # 找最早的有效截断点
        best = max_len
        for sep in ['。', '，', '——', '；', '、', '：']:
            idx = s.find(sep)
            if 4 <= idx <= max_len and idx < best:
                best = idx
        return s[:best]

    # 1. 优先取 ## 标题
    for _, m in re.findall(r'^(#{2,3})\s+(.+)$', content, re.MULTILINE):
        m = re.sub(r'^[❌✅⚠️💡🔥⚡️🏦📏📐📊🔗🤔🧩🔧🛡👁📌🔑①②③④⑤]+\s*', '', m)
        m = re.sub(r'^\d+[\.、]\s*', '', m)
        m = clean(m)
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 2. emoji 行内标题（如 "📏 4条活命规则"、"🔧 4种实战用法"）
    for m in re.findall(
        r'^[\U0001F300-\U0001FAFF\u2600-\u27BF\u2700-\u27BF❌✅⚠️]+\s*(.+)$',
        content, re.MULTILINE
    ):
        m = clean(m)
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 3. 取 **粗体**
    LABEL_WORDS = re.compile(r'^(表现|为什么|正确做法|建议|注意|结果|操作|当前|说到底)')
    for m in re.findall(r'\*\*([^*]+)\*\*', content):
        m = clean(m)
        if LABEL_WORDS.match(m):
            continue
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 4. 编号列表项（1. 2. 3. / ① ② ③），截取第一个短句
    for m in re.findall(r'^[①②③④⑤\d][\.、]?\s+(.+)$', content, re.MULTILINE):
        m = truncate_to_phrase(clean(m))
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 5. · 列表项
    for m in re.findall(r'^[·•]\s+(.+)$', content, re.MULTILINE):
        m = truncate_to_phrase(clean(m))
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 6. Markdown 破折号列表项（- xxx）
    for m in re.findall(r'^- (.+)$', content, re.MULTILINE):
        m = truncate_to_phrase(clean(m))
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 7. 兜底：引号短语（"xxx"）
    for m in re.findall(r'["""]([^"""]+)["""]', content):
        m = m.strip()
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


# PA 系列美元素材路径（抠图后的揉皱百元钞票）
PA_DOLLAR_IMG = Path.home() / "Downloads/333_cutout.png"

def _draw_rounded_rect(draw, xy, radius, fill):
    """圆角矩形（兼容旧版 PIL）"""
    x1, y1, x2, y2 = xy
    r = radius
    draw.ellipse([x1, y1, x1+2*r, y1+2*r], fill=fill)
    draw.ellipse([x2-2*r, y1, x2, y1+2*r], fill=fill)
    draw.ellipse([x1, y2-2*r, x1+2*r, y2], fill=fill)
    draw.ellipse([x2-2*r, y2-2*r, x2, y2], fill=fill)
    draw.rectangle([x1+r, y1, x2-r, y2], fill=fill)
    draw.rectangle([x1, y1+r, x2, y2-r], fill=fill)


# ─── 模板 C：pa 深色高级风（Price Action 系列教程）──────────────────────────
# 排版规则（定稿 2026-03-09，依据 PA定稿_深色高级_02.jpg 模板）：
#   顶部：半透明圆角标签栏，文字居中加粗
#   两道分割线（强调色 + 边框色）
#   超大主标题（填满宽度，强调色）
#   3 条粗体要点（实心圆点 + 白色文字）
#   揉皱美元图居中贴在要点下方（0.8× 缩放）
#   底部：@Wick123 左 | PA系列 #NN 右
def _render_pa(title: str, content: str, index: int) -> Image.Image:
    bg_c, border_c, accent, text_c = PA_THEMES[index % len(PA_THEMES)]
    MARGIN = 60

    img = Image.new("RGB", (W, H), bg_c)
    draw = ImageDraw.Draw(img)

    # ── 外边框 10px ───────────────────────────────────────────────
    BW = 10
    draw.rectangle([BW//2, BW//2, W - BW//2, H - BW//2],
                   outline=border_c, width=BW)

    # ── 顶部标签栏（半透明圆角矩形，文字水平居中）────────────────
    TAG_Y, TAG_H = 44, 68
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    _draw_rounded_rect(odraw, [MARGIN, TAG_Y, W - MARGIN, TAG_Y + TAG_H],
                       8, (*border_c, 110))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    tag_font = _font(FONT_BOLD, 34)
    tag_text = "PriceAction  技术分析系列教程"
    tw = tag_font.getbbox(tag_text)[2] - tag_font.getbbox(tag_text)[0]
    draw.text(((W - tw) // 2, TAG_Y + (TAG_H - _line_h(tag_font, tag_text)) // 2),
              tag_text, font=tag_font, fill=text_c)

    # ── 两道分割线 ────────────────────────────────────────────────
    sep_y = TAG_Y + TAG_H + 16
    draw.rectangle([MARGIN, sep_y, W - MARGIN, sep_y + 3], fill=accent)
    draw.rectangle([MARGIN, sep_y + 9, W - MARGIN, sep_y + 10], fill=border_c)

    # ── 主标题（自适应字号，填满宽度，强调色）────────────────────
    clean_title = re.sub(
        r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s：:·\-—()（）【】%！!？?]',
        '', title
    ).strip()
    avail_w = W - MARGIN * 2
    title_font = _font(FONT_BOLD, 80)       # 兜底
    for fs in range(160, 79, -2):
        f = _font(FONT_BOLD, fs)
        bb = f.getbbox(clean_title)
        if (bb[2] - bb[0]) <= avail_w:
            title_font = f
            break
    title_y = sep_y + 30
    draw.text((MARGIN, title_y), clean_title, font=title_font, fill=accent)
    title_y += _line_h(title_font, clean_title)

    # ── 要点列表（粗体 54px，实心圆点，下移 60px）───────────────
    bullet_y = title_y + 60
    points = extract_key_points(content) if content else []
    if not points:
        points = ["结构 · 流动性 · 订单块"]
    pt_font = _font(FONT_BOLD, 54)
    dot_r   = 9
    pt_lh   = _line_h(pt_font, "测") + 32
    cy = bullet_y
    for pt in points:
        dot_cy = cy + _line_h(pt_font, pt) // 2
        dot_cx = MARGIN + dot_r + 4
        draw.ellipse([dot_cx - dot_r, dot_cy - dot_r,
                      dot_cx + dot_r, dot_cy + dot_r], fill=accent)
        draw.text((MARGIN + dot_r * 2 + 16, cy), pt, font=pt_font, fill=text_c)
        cy += pt_lh

    # ── 美元图（裁剪透明边 → 缩放至下方区域 80% → 水平居中）────
    if PA_DOLLAR_IMG.exists():
        dollar_raw = Image.open(PA_DOLLAR_IMG).convert("RGBA")
        _, _, _, a_ch = dollar_raw.split()
        crop_box = a_ch.getbbox()
        dollar_crop = dollar_raw.crop(crop_box)

        d_top  = cy + 36
        d_bot  = H - 112
        tgt_h  = d_bot - d_top
        ratio  = tgt_h / dollar_crop.height
        tgt_w  = int(dollar_crop.width * ratio)
        if tgt_w > W - MARGIN:
            tgt_w = W - MARGIN
            ratio = tgt_w / dollar_crop.width
            tgt_h = int(dollar_crop.height * ratio)
        tgt_w = int(tgt_w * 0.8)
        tgt_h = int(tgt_h * 0.8)

        dollar_img = dollar_crop.resize((tgt_w, tgt_h), Image.LANCZOS)
        d_x = (W - tgt_w) // 2
        img.paste(dollar_img.convert("RGB"), (d_x, d_top), dollar_img)
        draw = ImageDraw.Draw(img)

    # ── 底部分割线 + 品牌 ─────────────────────────────────────────
    draw.rectangle([MARGIN, H - 105, W - MARGIN, H - 103], fill=border_c)

    bottom_y = H - 85
    brand_font = _font(FONT_LIGHT, 40)
    num_font   = _font(FONT_BOLD,  42)
    draw.text((MARGIN + 4, bottom_y), "@Wick123", font=brand_font, fill=(185, 195, 190))
    num_str = f"PA系列 #{index + 1:02d}"
    nb = num_font.getbbox(num_str)
    nw = nb[2] - nb[0]
    draw.text((W - MARGIN - nw, bottom_y), num_str, font=num_font, fill=accent)

    return img


# ─── 模板 D：broad_finance 泛财经风（白底斜纹 + 美元撕纸图）─────────────────
BROAD_FINANCE_DOLLAR = Path.home() / "Downloads/美元.jpg"
BROAD_FINANCE_GREEN  = (22, 88, 44)


def _split_title_bf(title: str) -> list[str]:
    parts = re.split(r'(?<=[？。！，；：—])', title)
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        return parts
    mid = len(title) // 2
    return [title[:mid], title[mid:]]


def _render_broad_finance(title: str, content: str = "", index: int = 0) -> Image.Image:
    GREEN = BROAD_FINANCE_GREEN
    img   = Image.new("RGB", (W, H), (255, 255, 255))
    draw  = ImageDraw.Draw(img)

    # 斜线底纹（稍深灰色 45°细线）
    for offset in range(-H, W + H, 28):
        draw.line([(offset, 0), (offset + H, H)], fill=(200, 200, 200), width=1)

    # 底部美元图（缩小 20%，向左偏移 15px）
    IMG_H = 560
    IMG_Y = H - IMG_H
    if BROAD_FINANCE_DOLLAR.exists():
        dollar = Image.open(BROAD_FINANCE_DOLLAR).convert("RGB")
        dw, dh = dollar.size
        # 缩小到 80% 宽度
        new_w = int(W * 0.8)
        new_h = int(dh * new_w / dw)
        resized = dollar.resize((new_w, new_h), Image.LANCZOS)
        if new_h > IMG_H:
            crop_top = (new_h - IMG_H) // 2
            cropped = resized.crop((0, crop_top, new_w, crop_top + IMG_H))
            paste_h = IMG_H
        else:
            cropped = resized
            paste_h = new_h
            IMG_Y = H - paste_h
        # 水平居中再左移 15px
        paste_x = (W - new_w) // 2 - 15
        img.paste(cropped, (paste_x, IMG_Y))
        # 渐变遮罩（覆盖图片上边缘）
        gradient = Image.new("L", (W, 90), 0)
        for i in range(90):
            ImageDraw.Draw(gradient).line([(0, i), (W, i)], fill=int(255 * (1 - i / 90)))
        img.paste(Image.new("RGB", (W, 90), (255, 255, 255)), (0, IMG_Y), gradient)

    draw = ImageDraw.Draw(img)

    # 四边绿色边框
    BW = 12
    draw.rectangle([(0, 0),      (W, BW)],  fill=GREEN)
    draw.rectangle([(0, H - BW), (W, H)],   fill=GREEN)
    draw.rectangle([(0, 0),      (BW, H)],  fill=GREEN)
    draw.rectangle([(W - BW, 0), (W, H)],   fill=GREEN)

    # 品牌名（左上）
    f_brand = _font(FONT_BOLD, 36)
    draw.text((60, 55), "美股研习社", font=f_brand, fill=GREEN, anchor="lm")
    bw = int(draw.textlength("美股研习社", font=f_brand))
    draw.rectangle([(60, 74), (60 + bw, 77)], fill=GREEN)

    # 主标题（断句两行，自适应字号，居中）
    t_lines = _split_title_bf(title)
    MAX_TW  = W - 100
    f_title = _font(FONT_BOLD, 64)
    for size in range(108, 60, -4):
        f = _font(FONT_BOLD, size)
        if all(draw.textlength(l, font=f) <= MAX_TW for l in t_lines):
            f_title = f
            break
    bbox   = f_title.getbbox("国")
    char_h = bbox[3] - bbox[1]
    t_gap  = int(char_h * 0.35)
    title_h = len(t_lines) * char_h + (len(t_lines) - 1) * t_gap

    # Bullet points：优先取 ## 标题，按宽度截断，最多3条
    def _bf_points(text: str) -> list[str]:
        pts = []
        for m in re.findall(r'^#{2,3}\s+(.+)$', text, re.MULTILINE):
            m = re.sub(r'^\d+[\.、]\s*', '', m).strip()
            m = re.sub(r'^[❌✅⚠️💡🔥①②③④⑤]+\s*', '', m).strip()
            if len(m) >= 4:
                pts.append(m)
            if len(pts) >= 3:
                break
        if not pts:
            pts = extract_key_points(text)
        return pts
    points  = _bf_points(content) if content else []
    f_pt    = _font(FONT_LIGHT, 42)
    pt_lh   = f_pt.getbbox("国")[3] - f_pt.getbbox("国")[1]
    pt_gap  = 18
    bullets_h = len(points) * (pt_lh + pt_gap) + (24 if points else 0)  # 24 = title→bullets gap

    # 整体内容块垂直居中（品牌区下方 100px 到图片上方 80px）
    content_h = title_h + bullets_h
    y_top     = 100
    y_bot     = IMG_Y - 80
    y_start   = (y_top + y_bot - content_h) // 2

    # 绘制标题
    for i, line in enumerate(t_lines):
        y = y_start + i * (char_h + t_gap)
        draw.text((W // 2, y + char_h // 2), line,
                  font=f_title, fill=(15, 15, 15), anchor="mm")

    # 绘制 bullet points
    if points:
        by = y_start + title_h + 24
        for pt in points:
            # 截断过长文字使其不超出边框
            max_pt_w = W - 130 - 12  # 12 = 右边框
            while len(pt) > 2 and draw.textlength(pt, font=f_pt) > max_pt_w:
                pt = pt[:-1]
            draw.text((80, by), "·", font=f_pt, fill=GREEN)
            draw.text((114, by), pt, font=f_pt, fill=(40, 40, 40))
            by += pt_lh + pt_gap

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
    elif category == "pa":
        img = _render_pa(title, content, index)
    elif category == "broad_finance":
        img = _render_broad_finance(title, content, index)
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
